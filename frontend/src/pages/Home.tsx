/**
 * 홈 화면 (피그마 1:2).
 * 위에서부터: 헤더 → 인사말 → 지역 바 → 질문 입력 카드 → "이렇게 물어보세요"(피그마 안내 예시 토글 카드)
 *            → 자주 찾는 복지 4개 → 129 전화 카드
 * - 지역을 고르기 전에는 "질문하기" 버튼이 비활성화되고 이유를 알려 줍니다.
 * - 🎤 버튼은 자리만 있습니다(음성 입력은 다음 단계).
 * - "현재 위치로 찾기": 누를 때만 브라우저 위치를 묻고(자동 요청·추적 없음) 좌표를 서버에 보내 지역으로 바꿉니다.
 *   서버(카카오 로컬 API, Codex 담당)가 아직 없어서 지금은 "준비 중" 안내가 나옵니다. ?dev=locate_ok 로 확인 흐름만 볼 수 있습니다.
 *   변환된 지역은 "사시는 곳과 같나요?" 확인을 거쳐야 적용되고, 실패해도 이미 고른 지역은 지우지 않습니다.
 *   서울·경기·전남 밖이면 그 지역으로는 못 하고, "전국 공통" 또는 직접 선택만 권합니다.
 * - 예시 질문 버튼은 입력칸만 채우고 자동으로 보내지 않습니다.
 * - "질문하기"는 /chat 대화 화면으로 갑니다. 질문은 주소가 아니라 라우터 state 로 넘깁니다.
 */
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { isAbortError, locateRegion } from '../api'
import { keepDevParam } from '../api/devScenario'
import { isServiceSido, QUICK_POLICIES } from '../api/fixtures'
import BigButton from '../components/BigButton'
import Header from '../components/Header'
import PhoneButton from '../components/PhoneButton'
import RegionSheet from '../components/RegionSheet'
import { GeoError, getCurrentCoords } from '../lib/geolocation'
import { loadRegion, saveRegion } from '../lib/regionStorage'
import { clearSessionId } from '../lib/chatSession'
import { HOME_EXAMPLES } from '../lib/examples'
import { formatRegion } from '../lib/searchParams'
import { ApiError, QUESTION_MAX_LENGTH, type LocatedRegion, type RegionSelection } from '../types/view'

/** 자주 찾는 복지: 정책 상세 페이지 대신 RAG 챗봇에 보낼 첫 질문. 실제 안내는 LLM이 생성한다. */
const QUICK_GUIDE_QUESTIONS: Record<string, string> = {
  'central:WLF00001164': '기초연금 제도를 일반적으로 안내해 주세요. 지원 대상, 지원 내용, 신청 장소와 방법을 근거 문서에 따라 설명해 주세요. 이후 궁금한 사항은 이어서 질문할게요.',
  'central:WLF00003191': '노인맞춤돌봄서비스를 일반적으로 안내해 주세요. 어떤 도움을 받을 수 있는지, 지원 대상과 신청 방법을 근거 문서에 따라 설명해 주세요. 이후 궁금한 사항은 이어서 질문할게요.',
  'central:WLF00001155': '노인 일자리 및 사회활동 지원사업을 일반적으로 안내해 주세요. 참여 대상, 활동 종류, 신청 방법을 근거 문서에 따라 설명해 주세요. 이후 궁금한 사항은 이어서 질문할게요.',
  'central:WLF00001170': '노인장기요양보험과 장기요양 지원을 일반적으로 안내해 주세요. 인정 신청 대상, 지원 서비스, 신청 절차를 근거 문서에 따라 설명해 주세요. 이후 궁금한 사항은 이어서 질문할게요.',
}

/** 현재 위치 찾기 진행 상태 */
type LocateState =
  | { status: 'idle' }
  | { status: 'locating' } // 브라우저 위치 확인 중
  | { status: 'converting' } // 좌표 → 지역 변환 중
  | { status: 'found'; region: LocatedRegion } // 변환 성공, 사용자 확인 대기
  | { status: 'error'; message: string }

/** 위치(조준선) 아이콘. 패키지 없이 인라인 SVG. 글자색을 따라가고 글씨 크기에 맞춰 커집니다 */
function CrosshairIcon() {
  return (
    <svg aria-hidden viewBox="0 0 24 24" className="size-6 shrink-0" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
      <circle cx="12" cy="12" r="7" />
      <circle cx="12" cy="12" r="2.5" fill="currentColor" stroke="none" />
      <path d="M12 2v3M12 19v3M2 12h3M19 12h3" />
    </svg>
  )
}

export default function Home() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const [region, setRegion] = useState<RegionSelection | null>(() => loadRegion())
  const [sheetOpen, setSheetOpen] = useState(false)
  const [pendingQuickQuestion, setPendingQuickQuestion] = useState<string | null>(null)
  // 결과 화면에서 "질문 고치기"로 돌아오면 ?q=에 이전 질문이 들어 있어 그대로 채웁니다
  const [question, setQuestion] = useState(() => params.get('q') ?? '')
  const [hint, setHint] = useState<string | null>(null)
  const [locate, setLocate] = useState<LocateState>({ status: 'idle' })
  const locateAbort = useRef<AbortController | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // 페이지를 떠나면 진행 중인 위치 조회·변환을 취소
  useEffect(() => () => locateAbort.current?.abort(), [])

  const trimmed = question.trim()
  const canSubmit = Boolean(region) && trimmed.length > 0 && trimmed.length <= QUESTION_MAX_LENGTH
  const locateBusy = locate.status === 'locating' || locate.status === 'converting'

  /** 새 주제로 안내를 시작할 때는 이전 챗 세션을 물려받지 않는다. */
  function openGuideChat(initialQuestion: string) {
    clearSessionId()
    const search = keepDevParam(new URLSearchParams()).toString()
    navigate(`/chat${search ? `?${search}` : ''}`, {
      state: { question: initialQuestion },
    })
  }

  /** 선택 지역을 저장한 뒤, 누른 복지 안내가 있다면 바로 채팅을 시작한다. */
  function handleSelectRegion(next: RegionSelection) {
    setRegion(next)
    saveRegion(next)
    setHint(null)
    setLocate({ status: 'idle' })
    if (pendingQuickQuestion) {
      const initialQuestion = pendingQuickQuestion
      setPendingQuickQuestion(null)
      openGuideChat(initialQuestion)
    }
  }

  function startQuickGuide(policyId: string) {
    const initialQuestion = QUICK_GUIDE_QUESTIONS[policyId]
    if (!initialQuestion) return
    if (!region) {
      setPendingQuickQuestion(initialQuestion)
      setSheetOpen(true)
      return
    }
    openGuideChat(initialQuestion)
  }

  /** "현재 위치로 찾기": 위치 확인 → 서버에서 지역 변환 → 사용자 확인(found) 순서. 실패해도 기존 지역은 유지 */
  async function handleLocate() {
    locateAbort.current?.abort()
    const controller = new AbortController()
    locateAbort.current = controller
    setLocate({ status: 'locating' })
    try {
      const coords = await getCurrentCoords(controller.signal)
      setLocate({ status: 'converting' })
      const found = await locateRegion(coords, { signal: controller.signal })
      setLocate({ status: 'found', region: found })
    } catch (err: unknown) {
      if (isAbortError(err)) return
      const message = err instanceof GeoError || err instanceof ApiError ? err.message : '위치를 확인하지 못했어요. 지역을 직접 선택해 주세요.'
      setLocate({ status: 'error', message })
    }
  }

  function applyLocated(found: LocatedRegion) {
    handleSelectRegion({ kind: 'region', sidoName: found.sidoName, sigunguName: found.sigunguName })
  }

  function fillExample(text: string) {
    setQuestion(text)
    setHint(null)
    textareaRef.current?.focus()
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (!region) {
      setHint('먼저 사시는 지역을 선택해 주세요.')
      setSheetOpen(true)
      return
    }
    if (!trimmed) {
      setHint('궁금한 내용을 적어 주세요.')
      return
    }
    // 질문은 주소에 넣지 않고 라우터 state 로 넘깁니다 (대화 화면이 받자마자 지움). ?dev= 만 주소로 유지
    const params = keepDevParam(new URLSearchParams())
    const search = params.toString()
    navigate(`/chat${search ? `?${search}` : ''}`, { state: { question: trimmed } })
  }

  return (
    <>
      <Header title="어르신 복지 안내" />
      <main className="px-[1.125rem] pb-10 pt-5">
        <h2 className="text-[1.75rem] font-bold leading-tight">어떤 복지가 궁금하세요?</h2>
        <p className="mt-2 text-lg leading-relaxed text-muted">조건을 말씀하시면 받을 수 있는 복지를 찾아드려요.</p>

        {/* 지역 바 */}
        <button
          type="button"
          onClick={() => setSheetOpen(true)}
          className={`mt-5 flex min-h-14 w-full items-center justify-between rounded-button border px-4 py-3 text-left ${
            region ? 'border-line bg-surface' : 'border-primary bg-primary-soft'
          }`}
        >
          <span className="flex items-center gap-2 text-lg font-bold">
            <span aria-hidden>📍</span>
            {formatRegion(region)}
          </span>
          <span className="text-base font-semibold text-primary-dark underline">{region ? '바꾸기' : '선택'}</span>
        </button>

        {/* 현재 위치로 찾기 (docs/claude-location-icon-request.md) */}
        <button
          type="button"
          onClick={handleLocate}
          disabled={locateBusy}
          aria-describedby="location-privacy location-status"
          className="mt-2 flex min-h-12 w-full items-center justify-center gap-2 rounded-button border-2 border-primary bg-surface px-4 py-2 text-lg font-bold text-primary-dark hover:bg-primary-soft disabled:opacity-60"
        >
          <CrosshairIcon />
          {locate.status === 'locating' ? '위치 확인 중…' : locate.status === 'converting' ? '지역 찾는 중…' : '현재 위치로 찾기'}
        </button>
        <p id="location-privacy" className="mt-1 text-sm leading-relaxed text-muted">
          누르면 현재 위치를 카카오에 보내 지역을 확인해요. 원하지 않으시면 지역을 직접 선택해 주세요.
        </p>
        <div id="location-status" role="status" aria-live="polite">
          {locate.status === 'error' && <p className="mt-1 text-base font-semibold text-accent-dark">{locate.message}</p>}
          {locate.status === 'found' && isServiceSido(locate.region.sidoName) && (
            <div className="mt-2 rounded-card border-2 border-primary bg-primary-soft p-4">
              <p className="text-base font-semibold text-primary-dark">지금 계신 곳</p>
              <p className="mt-1 text-xl font-bold">
                📍 {locate.region.sidoName} {locate.region.sigunguName ?? ''}
              </p>
              <p className="mt-1 text-base leading-snug text-muted">사시는 곳과 같나요? 복지는 사시는 곳 기준이에요.</p>
              <div className="mt-3 flex flex-col gap-2">
                <BigButton onClick={() => applyLocated(locate.region)}>네, 이 지역으로 할게요</BigButton>
                <BigButton variant="secondary" onClick={() => { setLocate({ status: 'idle' }); setSheetOpen(true) }}>
                  아니요, 직접 고를게요
                </BigButton>
              </div>
            </div>
          )}
          {locate.status === 'found' && !isServiceSido(locate.region.sidoName) && (
            <div className="mt-2 rounded-card border-2 border-accent bg-accent-soft p-4">
              <p className="text-base font-semibold text-accent-dark">지금 계신 곳</p>
              <p className="mt-1 text-xl font-bold">
                📍 {locate.region.sidoName} {locate.region.sigunguName ?? ''}
              </p>
              <p className="mt-1 text-base leading-snug text-muted">아직 서울·경기·전남 지역만 안내해 드려요. 전국 공통 복지는 볼 수 있어요.</p>
              <div className="mt-3 flex flex-col gap-2">
                <BigButton onClick={() => { setLocate({ status: 'idle' }); handleSelectRegion({ kind: 'nationwide' }) }}>전국 공통 복지만 볼게요</BigButton>
                <BigButton variant="secondary" onClick={() => { setLocate({ status: 'idle' }); setSheetOpen(true) }}>
                  지역을 직접 고를게요
                </BigButton>
              </div>
            </div>
          )}
        </div>

        {/* 질문 입력 카드 */}
        <form onSubmit={handleSubmit} className="mt-4 rounded-card border border-line bg-surface p-5 shadow-sm">
          <label htmlFor="question" className="block text-lg font-bold leading-snug">
            궁금한 것을 적어 주세요
          </label>
          <p className="mt-1 text-sm text-muted">음성으로 묻기(🎤)는 준비 중이에요</p>
          <div className="mt-3 flex items-stretch gap-2">
            <textarea
              id="question"
              ref={textareaRef}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              maxLength={QUESTION_MAX_LENGTH}
              rows={3}
              placeholder="예) 72세인데 받을 수 있는 복지 알려줘"
              className="min-h-24 flex-1 resize-none rounded-button border border-line bg-surface p-3 text-lg leading-relaxed placeholder:text-muted/70"
            />
            <button
              type="button"
              disabled
              aria-label="음성으로 질문하기 (준비 중)"
              title="음성 입력은 준비 중이에요"
              className="flex w-16 shrink-0 items-center justify-center rounded-button border-2 border-primary bg-surface text-3xl opacity-60"
            >
              🎤
            </button>
          </div>
          <p className="mt-1 text-right text-sm text-muted">
            {trimmed.length} / {QUESTION_MAX_LENGTH}
          </p>
          {hint && (
            <p role="alert" className="mt-1 text-base font-semibold text-accent-dark">
              {hint}
            </p>
          )}
          <BigButton type="submit" disabled={!canSubmit} className="mt-3 min-h-16! text-xl">
            🔎 질문하기
          </BigButton>
          {!region && <p className="mt-2 text-center text-sm text-muted">지역을 선택하면 질문할 수 있어요</p>}
        </form>

        {/* 이렇게 물어보세요 (피그마 안내 예시 토글 카드) */}
        <details className="mt-3 rounded-card border border-line bg-surface">
          <summary className="flex min-h-12 cursor-pointer items-center justify-between px-5 py-3 text-lg font-bold">
            <span>💬 이렇게 물어보세요</span>
            <span aria-hidden className="text-base font-semibold text-primary-dark">
              보기
            </span>
          </summary>
          <ul className="flex flex-col gap-2 px-5 pb-5">
            {HOME_EXAMPLES.map(({ text }) => (
              <li key={text}>
                <button
                  type="button"
                  onClick={() => fillExample(text)}
                  className="w-full rounded-button border border-line bg-surface-2 px-4 py-3 text-left text-base leading-snug hover:border-primary-dark hover:bg-primary-soft"
                >
                  “{text}”
                </button>
              </li>
            ))}
          </ul>
        </details>

        {/* 자주 찾는 복지 */}
        <h2 className="mt-8 text-xl font-bold">자주 찾는 복지</h2>
        <ul className="mt-3 grid grid-cols-2 gap-3">
          {QUICK_POLICIES.map((q) => (
            <li key={q.policyId}>
              <BigButton onClick={() => startQuickGuide(q.policyId)} variant="ghost" className="min-h-24 flex-col items-start! justify-start! text-left">
                <span aria-hidden className="text-2xl">
                  {q.emoji}
                </span>
                <span className="text-base leading-snug">{q.label}</span>
              </BigButton>
            </li>
          ))}
        </ul>

        {/* 129 전화 */}
        <section className="mt-8 rounded-card border-2 border-accent bg-surface p-5">
          <div className="flex items-center justify-between gap-3">
            <p className="text-lg font-bold leading-snug">전화로 바로 물어보고 싶으세요?</p>
            <p className="shrink-0 text-2xl font-bold text-accent-dark">☎ 129</p>
          </div>
          <p className="mt-1 text-base text-muted">보건복지상담센터 · 평일 상담 가능</p>
          <div className="mt-4">
            <PhoneButton contact={{ label: '보건복지상담센터', tel: '129' }} />
          </div>
        </section>
      </main>

      <RegionSheet
        open={sheetOpen}
        onClose={() => { setSheetOpen(false); setPendingQuickQuestion(null) }}
        onSelect={handleSelectRegion}
      />
    </>
  )
}
