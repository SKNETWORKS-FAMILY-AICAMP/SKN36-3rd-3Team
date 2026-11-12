/**
 * 개발·시연용 "상황 바꾸기".
 *
 * 개발 서버(npm run dev)에서 주소 뒤에 ?dev=이름 을 붙이면 mock이 그 상황을 재현합니다.
 *   예) http://localhost:5173/?dev=empty   → 결과 없음 화면 (대화 화면에서는 '근거 없음' 되묻기)
 *
 * - import.meta.env.DEV 가 false인 배포 빌드에서는 항상 null을 돌려주고,
 *   Vite가 빌드할 때 이 분기를 통째로 제거합니다. 어르신 화면에는 절대 노출되지 않습니다.
 * - 이름이 틀리면 그냥 정상 동작합니다.
 */

export const DEV_SCENARIOS = [
  'long_answer', // 10줄짜리 긴 답변 (레이아웃 확인)
  'empty', // 결과 없음 (no_results)
  'low_score', // 결과는 있었지만 점수 미달 (low_score)
  'guideline_only', // 정책 카드 없이 안내서 결과만
  'timeout', // 응답이 영영 오지 않음 (30초 타임아웃 확인)
  'server_error', // 서버 오류 (재시도 가능)
  'first_fail_then_ok', // 같은 질문 첫 번째는 실패, 두 번째부터 성공 (재시도 확인)
  'locate_ok', // 현재 위치 → 지역 변환이 성공한 것처럼 (서울특별시 강남구). 실제 서버 전까지 확인 흐름용
  // ── 대화 화면(/chat) 전용 ──
  'urgent', // 긴급 안내(safety_response) 화면. 어떤 질문이든 안전 안내로 답함
  'distress', // 정서적 어려움(distress) 공감 띠 + 보통 답변
  'no_memory', // 서버가 기억 기능을 끈 상태(session_id 없음) 안내 확인
] as const

export type DevScenario = (typeof DEV_SCENARIOS)[number]

function isDevScenario(value: string | null): value is DevScenario {
  return value !== null && (DEV_SCENARIOS as readonly string[]).includes(value)
}

/** 현재 주소의 ?dev= 값을 읽습니다. 개발 모드가 아니면 항상 null */
export function getDevScenario(): DevScenario | null {
  if (!import.meta.env.DEV) return null
  try {
    const value = new URLSearchParams(window.location.search).get('dev')
    return isDevScenario(value) ? value : null
  } catch {
    return null
  }
}

/** 페이지를 옮길 때 ?dev= 값을 함께 가져가기 위한 도우미 */
export function keepDevParam(params: URLSearchParams): URLSearchParams {
  const scenario = getDevScenario()
  if (scenario) params.set('dev', scenario)
  return params
}
