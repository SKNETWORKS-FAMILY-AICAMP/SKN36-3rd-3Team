/**
 * 대화 식별자(session_id) 보관.
 *
 * - sessionStorage 에만 둡니다: 탭(창)을 닫으면 사라지고 다른 탭과 공유되지 않습니다.
 *   localStorage·URL 에는 넣지 않습니다 (주소 복사·방문 기록에 남지 않게).
 * - 식별자는 "서버가 앞 대화를 찾는 열쇠"일 뿐 본인 확인(인증)이 아닙니다.
 *   같은 출처의 스크립트는 읽을 수 있으므로 보안 수단으로 기대하지 않습니다.
 * - 대화 내용(메시지)은 저장하지 않습니다. 새로고침하면 화면의 대화는 사라집니다.
 *   (기록 조회 API가 생기면 복원 — docs/claude-backend-questions-request.md b)
 * - 읽기·쓰기는 전부 try/catch: 사생활 보호 모드 등에서 저장소가 막혀 있어도 화면은 동작해야 합니다.
 */
const KEY = 'welfare.chat.sessionId'

export function loadSessionId(): string | null {
  try {
    const value = window.sessionStorage.getItem(KEY)
    return value && value.length <= 64 ? value : null
  } catch {
    return null
  }
}

export function saveSessionId(sessionId: string): void {
  try {
    window.sessionStorage.setItem(KEY, sessionId)
  } catch {
    /* 저장이 막혀 있으면 이번 화면에서만 기억 */
  }
}

export function clearSessionId(): void {
  try {
    window.sessionStorage.removeItem(KEY)
  } catch {
    /* 무시 */
  }
}
