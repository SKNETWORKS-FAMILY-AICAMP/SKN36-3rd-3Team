/**
 * 가짜 백엔드. 실제 서버 없이 화면을 확인하기 위한 구현입니다.
 *
 * - 바깥에서 보이는 모양(함수 이름, 인자, Promise, 오류 형태)은 나중에 만들 실제 HTTP
 *   구현과 같게 유지합니다. 그래야 페이지 코드를 거의 고치지 않고 교체할 수 있습니다.
 * - 취소(AbortSignal)를 지원합니다. 사용자가 지역을 바꾸거나 페이지를 떠나면 기다리던
 *   타이머를 정리하고 AbortError로 끝냅니다. 이건 "실패"가 아니라 "취소"입니다.
 * - 검색은 아주 단순합니다. 지역으로 후보를 거르고, 질문에 들어 있는 단어로 점수를 매깁니다.
 */
import type { AskResult, ChatReply, ChatSource, Fallback, GuidelineItem, LocatedRegion, PolicyDetail, RegionOption, RegionsData, RegionSelection, ResultItem, SafetyStatus, ScopeNotice } from '../types/view'
import { ApiError, QUESTION_MAX_LENGTH } from '../types/view'
import { GUIDELINES, POLICIES, REGIONS, stripGuidelineExtras, toPolicyDetail, toPolicyItem, type PolicyFixture } from './fixtures'
import { getDevScenario } from './devScenario'

export type RequestOptions = { signal?: AbortSignal }

/* ───────────── 공통 도우미 ───────────── */

function abortError(): DOMException {
  return new DOMException('요청이 취소되었습니다.', 'AbortError')
}

/** ms만큼 기다립니다. 중간에 취소되면 타이머를 정리하고 AbortError로 거부 */
function wait(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(abortError())
    const timer = window.setTimeout(() => {
      signal?.removeEventListener('abort', onAbort)
      resolve()
    }, ms)
    function onAbort() {
      window.clearTimeout(timer)
      reject(abortError())
    }
    signal?.addEventListener('abort', onAbort, { once: true })
  })
}

/** "응답 없음" 시나리오: 취소될 때까지 영영 끝나지 않는 Promise */
function never(signal?: AbortSignal): Promise<never> {
  return new Promise((_, reject) => {
    if (signal?.aborted) return reject(abortError())
    signal?.addEventListener('abort', () => reject(abortError()), { once: true })
  })
}

const NETWORK_DELAY_MS = 700

/* ───────────── 지역 ───────────── */

export async function getRegions(options: RequestOptions = {}): Promise<RegionsData> {
  await wait(300, options.signal)
  return REGIONS
}

function findRegion(sidoName: string): RegionOption | undefined {
  return REGIONS.regions.find((r) => r.sidoName === sidoName)
}

/** 지역 선택이 유효한지 검사. 유효하지 않으면 ApiError(retryable=false) */
function validateRegion(region: RegionSelection): RegionOption | null {
  if (region.kind === 'nationwide') return null
  const option = findRegion(region.sidoName)
  if (!option) throw new ApiError('invalid_request', '지역 이름이 올바르지 않아요. 지역을 다시 선택해 주세요.', false)
  if (region.sigunguName && option.sigungu.length > 0 && !option.sigungu.includes(region.sigunguName)) {
    throw new ApiError('invalid_request', '시·군·구가 올바르지 않아요. 지역을 다시 선택해 주세요.', false)
  }
  return option
}

function scopeNoticeFor(option: RegionOption | null): ScopeNotice | null {
  if (!option) return null
  if (option.status === 'unsupported') {
    return { reason: 'unsupported_region', message: '현재 서울·경기·전남 정책만 제공돼요. 전국 공통 정책만 보여드려요.' }
  }
  if (option.status === 'preparing') {
    return { reason: 'preparing_region', message: `${option.sidoName} 정책은 준비 중이에요. 지금은 전국 공통 정책만 보여드려요.` }
  }
  return null
}

/* ───────────── 검색 ───────────── */

/** 지역으로 후보를 거릅니다: 내 시군구 + 내 시도 전체 + 전국 공통 */
function candidatesFor(region: RegionSelection, option: RegionOption | null): PolicyFixture[] {
  return POLICIES.filter((p) => {
    if (p.sidoName === null) return true // 전국 공통
    if (region.kind === 'nationwide') return false
    if (option?.status !== 'active') return false
    if (p.sidoName !== region.sidoName) return false
    if (region.sigunguName === null || p.sigunguName === null) return true
    return p.sigunguName === region.sigunguName
  })
}

function score(question: string, keywords: string[]): number {
  const q = question.replace(/\s+/g, '')
  return keywords.reduce((n, k) => (q.includes(k.replace(/\s+/g, '')) ? n + 1 : n), 0)
}

const EMPTY_ANSWER = '말씀하신 내용과 맞는 복지 정책을 찾지 못했어요. 복지 상담이 필요하시면 129로 전화해 주세요.'
const NO_RESULTS: Fallback = { reason: 'no_results', message: '관련 정책을 찾지 못했어요. 129로 전화하시면 상담원이 도와드려요.' }
const LOW_SCORE: Fallback = { reason: 'low_score', message: '딱 맞는 정책을 찾지 못했어요. 129로 전화하시면 상담원이 도와드려요.' }

const LONG_ANSWER = [
  '혼자 지내시면서 일상생활이 힘드실 때 도움을 받을 수 있는 제도가 여러 가지 있어요.',
  '먼저 노인맞춤돌봄서비스는 안부 확인과 생활 지원을 해 드리는 서비스예요.',
  '식사를 거르기 쉬우시다면 경로식당이나 도시락 배달 사업도 있어요.',
  '소득이 적으시다면 기초연금 대상이 되실 수도 있어요.',
  '각 제도는 나이, 소득, 사시는 곳에 따라 받을 수 있는지가 달라요.',
  '그래서 정확한 안내는 가까운 주민센터에서 받아 보시는 것이 가장 좋아요.',
  '전화로 물어보고 싶으시면 129(보건복지상담센터)로 연락하시면 돼요.',
  '아래 카드에서 각 제도의 내용과 신청 방법을 보실 수 있어요.',
  '카드 안의 전화 버튼을 누르면 바로 전화가 걸려요.',
  '이 답변은 예시이며, 실제 서비스에서는 검색 결과에 따라 달라져요.',
].join('\n')

/** first_fail_then_ok 시나리오용: 한 번 실패한 질문 기록 (새로고침하면 초기화) */
const failedOnce = new Set<string>()

export async function ask(
  input: { question: string; region: RegionSelection },
  options: RequestOptions = {},
): Promise<AskResult> {
  const question = input.question.trim()
  if (!question) throw new ApiError('invalid_request', '질문을 입력해 주세요.', false)
  if (question.length > 300) throw new ApiError('invalid_request', '질문은 300자까지 입력할 수 있어요.', false)

  const scenario = getDevScenario()
  if (scenario === 'timeout') return never(options.signal)

  await wait(NETWORK_DELAY_MS, options.signal)

  if (scenario === 'server_error') {
    throw new ApiError('internal_error', '지금은 답변을 가져올 수 없어요. 잠시 후 다시 시도해 주세요.', true)
  }
  if (scenario === 'first_fail_then_ok') {
    const key = `${question}|${JSON.stringify(input.region)}`
    if (!failedOnce.has(key)) {
      failedOnce.add(key)
      throw new ApiError('backend_unavailable', '잠시 연결이 끊겼어요. 다시 시도해 주세요.', true)
    }
  }

  const option = validateRegion(input.region)
  const scopeNotice = scopeNoticeFor(option)

  const base: Omit<AskResult, 'answer' | 'items' | 'referenceCandidates' | 'fallback'> = {
    isExample: true,
    question,
    region: input.region,
    scopeNotice,
  }

  if (scenario === 'empty') return { ...base, answer: EMPTY_ANSWER, items: [], referenceCandidates: [], fallback: NO_RESULTS }
  if (scenario === 'low_score') return { ...base, answer: EMPTY_ANSWER, items: [], referenceCandidates: [], fallback: LOW_SCORE }

  const ranked = candidatesFor(input.region, option)
    .map((p) => ({ p, s: score(question, p.keywords) }))
    .filter((x) => x.s > 0)
    .sort((a, b) => b.s - a.s || (a.p.sidoName === null ? 1 : -1)) // 점수 같으면 지역 정책 우선

  const guidelineHits = GUIDELINES.filter((g) => score(question, g.keywords) > 0)
  const approved: GuidelineItem[] = []
  const pending: GuidelineItem[] = []
  for (const g of guidelineHits) (g.approval === 'approved' ? approved : pending).push(stripGuidelineExtras(g))

  if (scenario === 'guideline_only') {
    const only = GUIDELINES.map(stripGuidelineExtras).map((g) => ({ ...g, approval: 'approved' as const, badges: [{ label: `공식 안내서 p.${g.pageStart}~${g.pageEnd}`, tone: 'ok' as const }] }))
    return { ...base, answer: '공식 안내서에서 관련 내용을 찾았어요. 자세한 내용은 아래 안내서 항목을 확인해 주세요.', items: only, referenceCandidates: [], fallback: null }
  }

  if (ranked.length === 0 && approved.length === 0) {
    return { ...base, answer: EMPTY_ANSWER, items: [], referenceCandidates: pending, fallback: NO_RESULTS }
  }

  const items: ResultItem[] = [...ranked.map((x) => toPolicyItem(x.p)), ...approved]
  const answer = scenario === 'long_answer' ? LONG_ANSWER : ranked[0]?.p.exampleAnswer ?? '관련 안내서 내용을 찾았어요.'

  return { ...base, answer, items, referenceCandidates: pending, fallback: null }
}

/* ───────────── 현재 위치 → 지역 ───────────── */

/**
 * 좌표 → 지역 변환의 가짜 구현. 실제 요청은 api/http.ts가 서버(POST /api/location/region)로 보냅니다.
 * 이 함수는 개발 서버에서 ?dev=locate_ok 일 때만 쓰이며(확인 흐름 보기용) 서울특별시 강남구를 돌려줍니다.
 * 그 밖에는 "준비 중" 오류. 임의 지역을 성공인 것처럼 돌려주지 않고, 좌표를 저장하거나 콘솔에 찍지 않습니다.
 */
export async function locateRegion(coords: { latitude: number; longitude: number }, options: RequestOptions = {}): Promise<LocatedRegion> {
  if (!Number.isFinite(coords.latitude) || !Number.isFinite(coords.longitude)) {
    throw new ApiError('invalid_request', '위치 값이 올바르지 않아요.', false)
  }
  await wait(NETWORK_DELAY_MS, options.signal)
  if (getDevScenario() === 'locate_ok') return { sidoName: '서울특별시', sigunguName: '강남구', regionCode: '1168000000' }
  throw new ApiError('location_service_unavailable', '위치는 확인했지만 지역으로 바꾸는 기능은 준비 중이에요. 지역을 직접 선택해 주세요.', false)
}

/* ───────────── 대화 (origin/dev POST /api/chat 흉내) ───────────── */

/**
 * 서버(src/memory/*)처럼 "대화 식별자별 최근 메시지"를 기억합니다. 새로고침하면 사라집니다(서버는 PostgreSQL).
 * 실제 서버의 규칙을 그대로 따라 합니다:
 * - session_id 가 없으면 새로 만들어 돌려줌 (기억 기능이 켜진 경우에만; ?dev=no_memory 는 꺼진 상태)
 * - 안전 분류가 normal 이고 결과가 success/no_evidence 일 때만 질문·답변을 저장
 * - 짧은 후속 질문("그건", "그럼", "신청은" …)은 직전 내 질문을 검색 맥락으로 붙임
 * 지역은 서버 요청에 없으므로 여기서도 쓰지 않습니다. 메시지 본문을 콘솔·저장소에 남기지 않습니다.
 */
const chatSessions = new Map<string, Array<{ role: 'user' | 'assistant'; content: string }>>()
const MAX_HISTORY = 8

/** origin/dev src/agents/safety.py 와 같은 최소 규칙. 의학적 판단이 아닙니다 */
const SELF_HARM = /죽고\s*싶|자살\s*(?:하고\s*싶|할\s*거|하려)|목숨을\s*끊|스스로\s*목숨|나를\s*해치|자해\s*(?:하고\s*싶|할\s*거|하려)/
const HARM_OTHERS = /(?:사람|누군가|그\s*사람|저\s*사람|가족|이웃)(?:을|를)?\s*(?:죽이|해치|살해)|(?:죽여\s*버리|해쳐\s*버리)/
const DISTRESS = /(?:너무\s*)?외로워|고립된\s*느낌|우울해|우울합니다|살기\s*힘들|희망이\s*없|아무도\s*(?:안\s*찾아|찾아오지)|마음이\s*너무\s*힘들/

function classifySafety(question: string): { status: SafetyStatus; harmOthers: boolean } {
  const text = question.replace(/\s+/g, ' ').toLowerCase()
  if (SELF_HARM.test(text)) return { status: 'urgent', harmOthers: false }
  if (HARM_OTHERS.test(text)) return { status: 'urgent', harmOthers: true }
  if (DISTRESS.test(text)) return { status: 'distress', harmOthers: false }
  return { status: 'normal', harmOthers: false }
}

const URGENT_SELF =
  '많이 힘드신 상황인 것 같아요. 지금 혼자 감당하지 않으셔도 됩니다. 가능하면 가까이 있는 믿을 만한 사람에게 지금 상황을 알려 주세요. 스스로를 다치게 할 위험이 지금 있다면 한국에서는 119 또는 112에 즉시 연락해 주세요. 지금은 안전한 곳에 계신가요?'
const URGENT_OTHERS =
  '말씀해 주셔서 감사합니다. 지금 누군가를 다치게 할 가능성이 있다면 상대방과 거리를 두고 위험한 물건에서 멀어져 주세요. 위험이 임박했다면 한국에서는 112에 연락해 도움을 요청해 주세요. 지금 안전한 곳에 계신가요?'
/** 서버(welfare_answer.py)의 근거 없음 문장 그대로 */
const NO_EVIDENCE_ANSWER = '확인할 수 있는 복지정책 근거를 찾지 못했습니다. 지역이나 필요한 지원 종류를 조금 더 알려주시겠어요?'

const FOLLOWUP_WORDS = ['그건', '그거', '그 정책', '그 서비스', '거기', '그곳', '그럼', '그러면', '신청은', '대상은', '조건은']

function newSessionId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID()
  return `mock-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

export async function chat(input: { question: string; sessionId: string | null }, options: RequestOptions = {}): Promise<ChatReply> {
  const question = input.question.trim()
  if (!question) throw new ApiError('invalid_request', '질문을 입력해 주세요.', false)
  if (question.length > QUESTION_MAX_LENGTH) throw new ApiError('invalid_request', `질문은 ${QUESTION_MAX_LENGTH}자까지 입력할 수 있어요.`, false)

  const scenario = getDevScenario()
  if (scenario === 'timeout') return never(options.signal)
  await wait(NETWORK_DELAY_MS, options.signal)
  if (scenario === 'server_error') throw new ApiError('upstream_unavailable', 'AI 서비스 연결을 확인해 주세요. 잠시 후 다시 시도해 주세요.', true)

  const memoryEnabled = scenario !== 'no_memory'
  const sessionId = memoryEnabled ? (input.sessionId ?? newSessionId()) : null
  const history = sessionId ? (chatSessions.get(sessionId) ?? []) : []

  const safety = scenario === 'urgent' ? { status: 'urgent' as const, harmOthers: false } : classifySafety(question)
  const safetyStatus: SafetyStatus = scenario === 'distress' ? 'distress' : safety.status
  const base = { isExample: true, safetyStatus, sessionId }

  if (safetyStatus === 'urgent') {
    return { ...base, answer: safety.harmOthers ? URGENT_OTHERS : URGENT_SELF, sources: [], answerStatus: 'safety_response' }
  }

  // 짧은 후속 질문이면 직전 내 질문을 검색 맥락으로 붙임 (서버 build_search_question 과 같은 규칙)
  let searchText = question
  if (question.length <= 80 && FOLLOWUP_WORDS.some((w) => question.includes(w))) {
    const previous = [...history].reverse().find((m) => m.role === 'user')?.content
    if (previous) searchText = `${previous} ${question}`
  }

  const ranked =
    scenario === 'empty'
      ? []
      : POLICIES.map((p) => ({ p, s: score(searchText, p.keywords) }))
          .filter((x) => x.s > 0)
          .sort((a, b) => b.s - a.s)

  let reply: ChatReply
  if (ranked.length === 0) {
    reply = { ...base, answer: NO_EVIDENCE_ANSWER, sources: [], answerStatus: 'no_evidence' }
  } else {
    const top = ranked[0].p
    const sources: ChatSource[] = ranked.slice(0, 3).map(({ p }) => ({
      sourceType: 'policy',
      title: p.title,
      parentId: p.policyId,
      sourceUrl: p.sourceUrl,
      pageStart: null,
      pageEnd: null,
    }))
    const empathy = safetyStatus === 'distress' ? '힘든 마음을 이야기해 주셔서 감사해요. ' : ''
    reply = { ...base, answer: empathy + top.exampleAnswer, sources, answerStatus: 'success' }
  }

  // 서버와 같은 저장 조건: normal + success/no_evidence 일 때만
  if (sessionId && safetyStatus === 'normal' && (reply.answerStatus === 'success' || reply.answerStatus === 'no_evidence')) {
    const next = [...history, { role: 'user' as const, content: question }, { role: 'assistant' as const, content: reply.answer }]
    chatSessions.set(sessionId, next.slice(-MAX_HISTORY))
  }
  return reply
}

/* ───────────── 상세 ───────────── */

export async function getPolicy(policyId: string, options: RequestOptions = {}): Promise<PolicyDetail> {
  await wait(400, options.signal)
  const found = POLICIES.find((p) => p.policyId === policyId)
  if (!found) throw new ApiError('policy_not_found', '해당 정책 정보를 찾지 못했어요.', false)
  return toPolicyDetail(found)
}
