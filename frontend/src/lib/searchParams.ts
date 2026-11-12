/**
 * 결과 페이지 URL(/result?...)을 읽고 쓰는 규칙을 한곳에 모았습니다.
 *
 * 형태:
 *   /result?q=질문&scope=nationwide
 *   /result?q=질문&scope=region&sido=서울특별시
 *   /result?q=질문&scope=region&sido=서울특별시&sigungu=서대문구
 *
 * - URL은 "검색 조건"을 복원합니다. 답변 자체는 저장하지 않고 새로고침하면 다시 요청합니다.
 * - 질문(q)이 주소창에 남는 것은 공유·뒤로가기 편의를 위한 의도적 선택입니다.
 */
import { QUESTION_MAX_LENGTH, type RegionSelection } from '../types/view'

export type SearchQuery = { question: string; region: RegionSelection }

export type ParsedSearch =
  | { ok: true; value: SearchQuery }
  | { ok: false; reason: 'missing_question' | 'question_too_long' | 'missing_region' | 'invalid_region' }

export function buildSearchParams(query: SearchQuery): URLSearchParams {
  const params = new URLSearchParams()
  params.set('q', query.question)
  if (query.region.kind === 'nationwide') {
    params.set('scope', 'nationwide')
  } else {
    params.set('scope', 'region')
    params.set('sido', query.region.sidoName)
    if (query.region.sigunguName) params.set('sigungu', query.region.sigunguName)
  }
  return params
}

export function parseSearchParams(params: URLSearchParams): ParsedSearch {
  const question = (params.get('q') ?? '').trim()
  if (!question) return { ok: false, reason: 'missing_question' }
  if (question.length > QUESTION_MAX_LENGTH) return { ok: false, reason: 'question_too_long' }

  const scope = params.get('scope')
  if (scope === 'nationwide') {
    return { ok: true, value: { question, region: { kind: 'nationwide' } } }
  }
  if (scope === 'region') {
    const sidoName = (params.get('sido') ?? '').trim()
    const sigungu = (params.get('sigungu') ?? '').trim()
    if (!sidoName) return { ok: false, reason: 'invalid_region' }
    return {
      ok: true,
      value: { question, region: { kind: 'region', sidoName, sigunguName: sigungu || null } },
    }
  }
  return { ok: false, reason: 'missing_region' }
}

/** 지역 선택을 사람이 읽는 한 줄로 (예: "서울특별시 서대문구", "전국 공통") */
export function formatRegion(region: RegionSelection | null): string {
  if (!region) return '지역을 선택해 주세요'
  if (region.kind === 'nationwide') return '전국 공통 정책만'
  return region.sigunguName ? `${region.sidoName} ${region.sigunguName}` : `${region.sidoName} 전체`
}

/** 같은 검색인지 비교할 때 쓰는 키 (늦게 도착한 응답 무시 등) */
export function searchKey(query: SearchQuery): string {
  const r = query.region
  const regionKey = r.kind === 'nationwide' ? 'nationwide' : `${r.sidoName}|${r.sigunguName ?? ''}`
  return `${query.question}::${regionKey}`
}
