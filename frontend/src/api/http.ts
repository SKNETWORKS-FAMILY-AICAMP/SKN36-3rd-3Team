/** FastAPI HTTP adapter. No mock answers or invented policy details. */
import type { AnswerStatus, AskResult, ChatReply, ChatSource, FollowUp, GuidelineItem, PolicyDetail, RegionsData, RegionSelection, SafetyStatus, ScopeNotice } from '../types/view'
import { ApiError, QUESTION_MAX_LENGTH } from '../types/view'
import { REGIONS } from './fixtures'

export type RequestOptions = { signal?: AbortSignal }

type JsonObj = Record<string, unknown>
function obj(value: unknown): JsonObj | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as JsonObj : null
}
function str(value: unknown): string | null { return typeof value === 'string' ? value : null }
function num(value: unknown): number | null { return typeof value === 'number' && Number.isFinite(value) ? value : null }
function safeUrl(value: unknown): string | null {
  if (typeof value !== 'string') return null
  try {
    const u = new URL(value)
    return ['http:', 'https:'].includes(u.protocol) ? u.href : null
  } catch { return null }
}
function detailText(detail: unknown): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const parts = detail.map((entry) => obj(entry)?.msg).filter((v): v is string => typeof v === 'string')
    return parts.join('; ') || '요청 내용을 확인해 주세요.'
  }
  return '요청 처리 중 문제가 발생했어요.'
}

async function requestJson(path: string, init: RequestInit = {}): Promise<unknown> {
  let response: Response
  try {
    response = await fetch(path, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...init.headers },
    })
  } catch (error) {
    if (init.signal?.aborted) throw new DOMException('요청이 취소되었습니다.', 'AbortError')
    throw new ApiError('backend_unavailable', '서버에 연결하지 못했어요. FastAPI 실행 상태를 확인해 주세요.', true)
  }
  const raw: unknown = await response.json().catch(() => null)
  if (!response.ok) {
    const detail = obj(raw)?.detail
    const message = detailText(detail)
    if (response.status === 404) throw new ApiError('policy_not_found', '요청한 정보를 찾지 못했어요.', false)
    if (response.status === 422 || response.status === 400) throw new ApiError('invalid_request', message, false)
    if (response.status === 501) throw new ApiError('not_implemented', '해당 기능은 아직 서버에서 준비 중이에요.', false)
    throw new ApiError('backend_unavailable', response.status >= 500 ? 'AI 서비스 처리에 실패했어요. 잠시 후 다시 시도해 주세요.' : message, response.status >= 500 || response.status === 429)
  }
  return raw
}

function toSource(value: unknown): ChatSource | null {
  const s = obj(value)
  if (!s) return null
  const rawType = str(s.source_type)
  if (rawType !== 'policy' && rawType !== 'guideline') return null
  return {
    sourceType: rawType,
    title: str(s.title) || '제목 미확인 자료',
    parentId: str(s.parent_id),
    sourceUrl: safeUrl(s.source_url),
    pageStart: num(s.page_start),
    pageEnd: num(s.page_end),
  }
}

/** LLM clarify 결과의 제목과 버튼을 추출한다. no_evidence 일반 실패엔 선택지를 만들지 않는다. */
function toFollowUp(result: JsonObj, answerStatus: string | null): FollowUp | null {
  if (answerStatus !== 'no_evidence') return null
  const answer = str(result.answer) || ''
  const numbered = /^\s*(?:\d+)[.)]\s*(.+?)\s*$/gm
  const fromText = [...answer.matchAll(numbered)].map((match, index) => ({
    id: String(index + 1), label: match[1].trim(),
  }))
  const fromServer = Array.isArray(result.choices) ? result.choices.flatMap((item, index) => {
    const choice = obj(item)
    const label = str(choice?.label)?.trim()
    return label ? [{ id: str(choice?.id) || String(index + 1), label }] : []
  }) : []
  const choices = (fromServer.length >= 2 ? fromServer : fromText)
    .filter((choice) => choice.label.length > 0 && choice.label.length <= 200)
    .slice(0, 4)
  if (choices.length < 2) return null
  const firstNumberedLine = answer.search(/^\s*\d+[.)]\s+/m)
  if (firstNumberedLine < 0) return null
  const question = answer.slice(0, firstNumberedLine).trim()
    .replace(/^[-*#\s]+/, '')
  if (!question || question.length > 300) return null
  return { question, choices }
}

export async function chat(
  input: { question: string; sessionId: string | null; region?: RegionSelection | null },
  options: RequestOptions = {},
): Promise<ChatReply> {
  const question = input.question.trim()
  if (!question || question.length > QUESTION_MAX_LENGTH) {
    throw new ApiError('invalid_request', `질문은 1~${QUESTION_MAX_LENGTH}자로 입력해 주세요.`, false)
  }
  const result = obj(await requestJson('/api/chat', {
    method: 'POST',
    body: JSON.stringify({
      question,
      session_id: input.sessionId,
      region: input.region?.kind === 'region'
        ? { kind: 'region', sido_name: input.region.sidoName, sigungu_name: input.region.sigunguName }
        : { kind: 'nationwide' },
    }),
    signal: options.signal,
  }))
  if (!result || typeof result.answer !== 'string') {
    throw new ApiError('invalid_response', '서버의 답변 형식이 올바르지 않아요.', true)
  }
  const validStatuses = ['success', 'no_evidence', 'safety_response', 'error']
  const validSafety = ['normal', 'distress', 'urgent']
  const answerStatus = str(result.answer_status)
  const safetyStatus = str(result.safety_status)
  return {
    isExample: false,
    answer: result.answer,
    sessionId: str(result.session_id),
    answerStatus: validStatuses.includes(answerStatus || '') ? answerStatus as AnswerStatus : 'error',
    safetyStatus: validSafety.includes(safetyStatus || '') ? safetyStatus as SafetyStatus : 'normal',
    sources: Array.isArray(result.sources) ? result.sources.map(toSource).filter((s): s is ChatSource => s !== null) : [],
    followUp: toFollowUp(result, answerStatus),
  }
}

/** Temporary search bridge: uses live chat for an answer, but NOT verified region filtering or policy cards. */
export async function ask(
  input: { question: string; region: RegionSelection },
  options: RequestOptions = {},
): Promise<AskResult> {
  const region = input.region
  const regionLabel = region.kind === 'region'
    ? `${region.sidoName}${region.sigunguName ? ' ' + region.sigunguName : ''}`
    : null
  // Adding region context to the question is NOT a server-side filter.
  const q = regionLabel ? `${regionLabel}에서 받을 수 있는 복지 지원에 대해: ${input.question}` : input.question
  if (q.length > QUESTION_MAX_LENGTH) throw new ApiError('invalid_request', `지역을 포함한 질문은 ${QUESTION_MAX_LENGTH}자 이하여야 해요.`, false)
  const result = await chat({ question: q, sessionId: null }, options)
  const scopeNotice: ScopeNotice | null = regionLabel ? {
    reason: 'preparing_region',
    message: '현재 지역별 검색 필터는 서버에 연결되지 않았어요. 아래 답변은 선택 지역에 맞게 검증된 결과가 아닙니다. 거주지 주민센터에서 확인해 주세요.',
  } : null
  const seen = new Set<string>()
  const guidelines: GuidelineItem[] = []
  for (const s of result.sources) {
    if (s.sourceType !== 'guideline' || s.pageStart === null) continue
    const key = `${s.parentId || s.title}:${s.pageStart}:${s.pageEnd}`
    if (seen.has(key)) continue
    seen.add(key)
    guidelines.push({
      kind: 'guideline', documentId: s.parentId || s.title,
      documentTitle: s.title, sectionTitle: null,
      pageStart: s.pageStart ?? 0, pageEnd: s.pageEnd ?? s.pageStart ?? 0,
      pageExact: s.pageStart !== null && s.pageEnd !== null && s.pageStart === s.pageEnd,
      approval: 'approved', snippet: '챗봇 답변에서 인용한 안내서 자료입니다.',
      badges: [{ label: '검색 근거', tone: 'info' }], sourceUrl: s.sourceUrl,
    })
  }
  const noEvidence = result.answerStatus === 'no_evidence' || result.answerStatus === 'error'
  return {
    isExample: false, question: input.question, region, scopeNotice,
    answer: result.answer, items: guidelines, referenceCandidates: [],
    fallback: noEvidence ? { reason: 'no_results', message: '검증된 정책 검색 결과가 부족합니다. 필요한 조건을 더 구체적으로 알려주세요.' } : null,
  }
}

/** Static region chooser (NOT a server policy-coverage assertion). */
export async function getRegions(options: RequestOptions = {}): Promise<RegionsData> {
  if (options.signal?.aborted) throw new DOMException('요청이 취소되었습니다.', 'AbortError')
  return {
    serviceScope: REGIONS.serviceScope,
    regions: REGIONS.regions.map((r) => ({ ...r, status: 'preparing' })),
  }
}

/** No policy-detail endpoint yet; never show mock policies as real data. */
export async function getPolicy(_policyId: string, options: RequestOptions = {}): Promise<PolicyDetail> {
  if (options.signal?.aborted) throw new DOMException('요청이 취소되었습니다.', 'AbortError')
  throw new ApiError('not_implemented', '정책 상세조회 API가 아직 구현되지 않았어요. 검색 답변의 출처를 확인해 주세요.', false)
}
