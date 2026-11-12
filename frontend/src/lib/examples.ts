/**
 * 예시 질문(상황 문장) 목록 — 홈의 "이렇게 물어보세요"와 대화 화면의 상황 버튼이 같은 목록을 씁니다.
 *
 * - 문장은 "나의 상황"을 말하는 완성 문장입니다. 정책 이름·금액·자격(독거·나이·소득)을 단정하지 않습니다.
 * - 홈: 누르면 입력칸만 채웁니다. 대화 화면: 누르면 그 문장이 그대로 다음 내 메시지로 전송됩니다.
 * - 예시 데이터(mock)의 검색어와 맞는 문장만 두어 "근거 없음 → 상황 선택 → 답변"이 실제로 이어집니다.
 * - 순서 규칙은 표시 순서용 간단 규칙입니다(데이터 로직 아님). 한 글자 단어(일·약)는 오탐이 많아 쓰지 않습니다.
 */
export type ExampleQuestion = {
  /** 화면에 장식으로만 보이는 이모지 (aria-hidden). 없으면 null */
  emoji: string | null
  text: string
  /** 질문에 이 표현이 있으면 이 문장을 앞으로 보냅니다 */
  cues: string[]
}

export const EXAMPLE_QUESTIONS: ExampleQuestion[] = [
  { emoji: '🍚', text: '혼자 사는데 밥 챙겨 먹기 힘들어요', cues: ['밥', '배고', '식사', '반찬', '끼니'] },
  { emoji: '💰', text: '생활비로 쓸 돈을 지원받고 싶어요', cues: ['돈', '연금', '생활비', '수당'] },
  { emoji: null, text: '몸이 불편해서 돌봄이 필요해요', cues: ['아파', '불편', '돌봄', '거동', '치매'] },
  { emoji: '💼', text: '일자리를 찾고 있어요', cues: ['일자리', '일하고', '일할', '소일'] },
]

/** 홈 "이렇게 물어보세요"에 보여 줄 기본 3개 */
export const HOME_EXAMPLES = EXAMPLE_QUESTIONS.slice(0, 3)

/**
 * 대화 화면 상황 버튼용: 질문과 관련 있는 문장을 앞으로, 이미 보낸 문장은 빼고, 최대 limit개.
 * 처리 순서: 보낸 문장 제외 → 관련도 정렬(관련 있으면 앞, 나머지는 기본 순서) → 자르기
 */
export function pickSituations(question: string, alreadySent: string[], limit = 3): ExampleQuestion[] {
  const q = question.replace(/\s+/g, '')
  const sent = new Set(alreadySent.map((t) => t.trim()))
  return EXAMPLE_QUESTIONS.filter((e) => !sent.has(e.text))
    .map((e, index) => ({ e, index, hit: e.cues.some((c) => q.includes(c)) ? 0 : 1 }))
    .sort((a, b) => a.hit - b.hit || a.index - b.index)
    .slice(0, limit)
    .map((x) => x.e)
}
