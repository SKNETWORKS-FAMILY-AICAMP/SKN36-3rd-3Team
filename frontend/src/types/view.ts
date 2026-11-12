/**
 * 화면(UI)에서 쓰는 데이터 모양 = "뷰모델".
 *
 * - 이 파일은 "화면에 어떤 정보가 보이는가"만 정의합니다.
 * - 백엔드(RAG/FastAPI)의 실제 응답 형식과 1:1이 아닙니다. 나중에 연동할 때
 *   서버 응답 → 이 뷰모델로 바꾸는 변환 코드를 api/ 폴더에 따로 씁니다.
 * - 값이 없을 수 있는 것은 전부 `| null`로 표시합니다. 화면은 null일 때
 *   "확인 필요" 같은 문구를 보여 주고, 절대 값을 지어내지 않습니다.
 */

/** 배지 색 톤. warn=주황(확인 필요), info=회색(참고), ok=초록(안심) */
export type Tone = 'warn' | 'info' | 'ok'

export type Badge = { label: string; tone: Tone }

/** 전화 걸기 버튼에 쓰는 연락처. tel은 실제로 걸 수 있는 번호만 */
export type Contact = { label: string; tel: string }

/** 지역 지원 상태. active=검색 가능, preparing=서비스 범위지만 데이터 준비 중, unsupported=전국 공통만 */
export type RegionStatus = 'active' | 'preparing' | 'unsupported'

export type RegionOption = {
  sidoName: string
  status: RegionStatus
  sigungu: string[]
}

export type RegionsData = {
  /** 서비스 범위로 합의된 시도 이름 (서울·경기·전남) */
  serviceScope: string[]
  regions: RegionOption[]
}

/** 사용자가 고른 검색 범위 */
export type RegionSelection =
  | { kind: 'nationwide' }
  | { kind: 'region'; sidoName: string; sigunguName: string | null }

/** 정책 결과 1건 (카드) */
export type PolicyItem = {
  kind: 'policy'
  policyId: string
  title: string
  sidoName: string | null
  sigunguName: string | null
  snippet: string
  badges: Badge[]
  themes: string[]
}

/** 공식 안내서(PDF) 결과 1건. 상세 페이지가 없고 문서명·쪽 범위만 보여 줍니다 */
export type GuidelineItem = {
  kind: 'guideline'
  documentId: string
  documentTitle: string
  sectionTitle: string | null
  pageStart: number
  pageEnd: number
  /** false면 "p.13~17에 수록"처럼 범위로 표시 */
  pageExact: boolean
  /** approved=근거로 인용 가능, pending=검토 중 참고자료 */
  approval: 'approved' | 'pending'
  snippet: string
  badges: Badge[]
  sourceUrl: string | null
}

export type ResultItem = PolicyItem | GuidelineItem

/** 검색 범위에 대한 안내 (예: 미지원 지역이라 전국 공통만 보여 줌). 결과 유무와 무관 */
export type ScopeNotice = {
  reason: 'unsupported_region' | 'preparing_region'
  message: string
}

/** 최종 결과가 없을 때의 이유 */
export type Fallback = {
  reason: 'no_results' | 'low_score'
  message: string
}

/** 질문 1번에 대한 답변 전체 */
export type AskResult = {
  /** true면 화면 위에 "예시 답변입니다" 띠를 띄웁니다 */
  isExample: boolean
  question: string
  region: RegionSelection
  scopeNotice: ScopeNotice | null
  answer: string
  items: ResultItem[]
  /** 승인 전 안내서 참고자료. 화면에서는 접어 둡니다 */
  referenceCandidates: GuidelineItem[]
  fallback: Fallback | null
}

/** 정책 상세 페이지 */
export type PolicyDetail = {
  isExample: boolean
  policyId: string
  title: string
  summary: string | null
  sidoName: string | null
  sigunguName: string | null
  badges: Badge[]
  /**
   * 한눈에 보기 요약 (서버가 적재 시 1회 생성 → 검수 승인된 것만 내려옴, 계약 T8).
   * 승인 전·누락이면 null → 화면은 "기관에 문의"로 대체하고 원문을 바로 보여 줍니다.
   * 자격을 단정하지 않고, 기관 업무 단계를 "n단계"로 바꾸지 않습니다.
   */
  highlights: { who: string | null; what: string | null; how: string | null }
  /**
   * 요약 카드에 크게 보여 줄 핵심 숫자. 원문에 있는 숫자만, 명칭·단위·조건을 함께 적을 수 있을 때만.
   * 예) "기준연금액 월 349,700원 · 실제 받는 금액은 달라질 수 있어요". 못 적으면 null(표시 안 함).
   */
  keyFigure: string | null
  /** 누가 받을 수 있나요 (원문) */
  targetText: string | null
  selectionCriteriaText: string | null
  /** 어떤 지원인가요 (금액은 여기 원문에만) */
  benefitText: string | null
  /** 어떻게 신청하나요 */
  applicationText: string | null
  department: string | null
  /** 정책 연락처. 비어 있으면 화면이 129만 보여 줍니다 */
  contacts: Contact[]
  /** 전화번호 형식이 아닌 원문 연락처 (예: 내선 "5447") */
  contactNote: string | null
  relatedForms: Array<{ name: string; url: string }>
  sourceUrl: string | null
  startDate: string | null
  endDate: string | null
  sources: GuidelineItem[]
  referenceCandidates: GuidelineItem[]
}

/** 좌표 → 행정구역 변환 결과 (서버가 카카오 로컬 API로 변환, 계약 §8.5 초안). 현재 위치일 뿐 거주지가 아닐 수 있음 */
export type LocatedRegion = {
  sidoName: string
  sigunguName: string | null
  regionCode: string | null
}

/* ───────────── 대화(채팅) ─────────────
 * origin/dev 서버(src/api/main.py POST /api/chat)의 응답을 보고 적은 UI용 모양입니다. 확정 계약이 아닙니다.
 * - 서버는 question + session_id만 받습니다(지역 필드 없음). 지역 전송은 백엔드 답을 기다리는 중(docs/claude-backend-questions-request.md).
 * - UI는 answer_status 로 화면을 나눕니다. 서버가 아직 "정보 부족"과 "근거 없음"을 구분해 주지 않습니다.
 */

/** 서버 답변 상태. success=근거 있는 답 / no_evidence=근거 못 찾음(되묻기) / safety_response=긴급 안내 / error=생성 실패 */
export type AnswerStatus = 'success' | 'no_evidence' | 'safety_response' | 'error'

/** 안전 분류. normal / distress(정서적 어려움: 공감 띠) / urgent(긴급: 안전 안내 우선) */
export type SafetyStatus = 'normal' | 'distress' | 'urgent'

/** 답변이 참고한 자료 1건 (서버 sources[] 항목에서 화면에 필요한 것만) */
export type ChatSource = {
  sourceType: 'policy' | 'guideline'
  title: string
  /** 정책 id 등. 상세 API가 아직 없어 화면에서는 링크로 쓰지 않습니다 */
  parentId: string | null
  /** http/https 만 링크로 표시합니다 */
  sourceUrl: string | null
  pageStart: number | null
  pageEnd: number | null
}

/** Agent가 되묻는 질문에 대해 제공한 실제 선택지 (하드코딩하지 않음) */
export type FollowUpChoice = { id: string; label: string }

export type FollowUp = { question: string; choices: FollowUpChoice[] }

/** 서버 답변 1회분 */
export type ChatReply = {
  /** true면 예시 데이터(mock) */
  isExample: boolean
  answer: string
  sources: ChatSource[]
  answerStatus: AnswerStatus
  safetyStatus: SafetyStatus
  /**
   * 이 대화의 식별자. 다음 질문에 그대로 보내면 서버가 앞 대화를 읽어 이어 줍니다.
   * null이면 서버가 기억 기능을 끈 상태(이번 대화는 기억되지 않음).
   */
  sessionId: string | null
  /** 의도 분석 Agent가 추가 정보를 요청할 때만 존재 */
  followUp?: FollowUp | null
}

/** api 함수들이 실패할 때 던지는 오류. retryable=false면 "다시 시도" 대신 다른 행동을 권합니다 */
export class ApiError extends Error {
  code: string
  retryable: boolean
  constructor(code: string, message: string, retryable: boolean) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.retryable = retryable
  }
}

/** 질문 글자 수 제한 */
export const QUESTION_MAX_LENGTH = 300
