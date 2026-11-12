/**
 * 대화 화면 (/chat). 홈에서 첫 질문을 받아 시작하고, 같은 화면에서 계속 이어서 질문합니다.
 *
 * 구조 (초보자용 설명)
 * - 화면에 보이는 메시지 목록(messages)은 이 컴포넌트의 메모리에만 있습니다. 새로고침하면 사라집니다.
 * - "두 번째 질문"은 새 페이지가 아니라, 같은 대화 식별자(sessionId)로 서버에 한 번 더 묻는 것입니다.
 *   서버가 그 식별자로 앞 대화를 읽어 이어 줍니다. 앞 질문·답변을 UI가 다시 보내지 않습니다.
 * - 질문·지역은 주소(URL)에 넣지 않습니다. 첫 질문은 홈에서 라우터 state 로 받고, 받자마자 지웁니다
 *   (뒤로가기·새로고침으로 같은 질문이 자동으로 다시 전송되지 않게).
 * - 요청은 "보낼 것(pending)"이 생길 때마다 useEffect 가 한 번 보냅니다. 페이지를 떠나면 취소합니다.
 *   30초가 지나면 시간 초과로 처리합니다.
 *
 * 아직 안 하는 것 (백엔드 답 대기, docs/claude-backend-questions-request.md)
 * - 지역을 서버에 보내기, 새로고침 뒤 대화 복원, 서버 기록 삭제, 실제 서버 연결(지금은 mock).
 */
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { chat, isAbortError } from '../api'
import AssistantCard from '../components/AssistantCard'
import BigButton from '../components/BigButton'
import ErrorBox from '../components/ErrorBox'
import Header from '../components/Header'
import PhoneButton from '../components/PhoneButton'
import SituationChips from '../components/SituationChips'
import { clearSessionId, loadSessionId, saveSessionId } from '../lib/chatSession'
import { loadRegion } from '../lib/regionStorage'
import { ApiError, QUESTION_MAX_LENGTH, type ChatReply } from '../types/view'

const TIMEOUT_MS = 120_000

type Message = { id: number; role: 'user'; text: string } | { id: number; role: 'assistant'; reply: ChatReply }

type SendState =
  | { status: 'idle' }
  | { status: 'sending' }
  | { status: 'error'; text: string; message: string; retryable: boolean }

/** 홈에서 넘어올 때 라우터 state 에 담기는 값 */
type IncomingState = { question?: unknown } | null

function readIncomingQuestion(state: unknown): string | null {
  const s = state as IncomingState
  const q = s && typeof s === 'object' && typeof s.question === 'string' ? s.question.trim() : ''
  return q && q.length <= QUESTION_MAX_LENGTH ? q : null
}

export default function Chat() {
  const location = useLocation()
  const navigate = useNavigate()
  const region = loadRegion()

  const nextId = useRef(1)
  const sessionRef = useRef<string | null>(loadSessionId())
  /** 이 탭에 이전 대화 식별자가 있었는데 화면이 비어 있음 = 새로고침·재진입 */
  const [hadPreviousSession] = useState(() => sessionRef.current !== null)
  const [memoryOff, setMemoryOff] = useState(false)

  // 첫 질문: 홈에서 state 로 받은 것을 "보낼 것"과 메시지 목록에 넣고 시작
  const [initialQuestion] = useState(() => readIncomingQuestion(location.state))
  const [messages, setMessages] = useState<Message[]>(() =>
    initialQuestion ? [{ id: nextId.current++, role: 'user', text: initialQuestion }] : [],
  )
  const [pending, setPending] = useState<{ id: number; text: string } | null>(() =>
    initialQuestion ? { id: 0, text: initialQuestion } : null,
  )
  const [send, setSend] = useState<SendState>(initialQuestion ? { status: 'sending' } : { status: 'idle' })

  const [draft, setDraft] = useState('')
  const [draftError, setDraftError] = useState<string | null>(null)
  const [confirmReset, setConfirmReset] = useState(false)
  const [focusId, setFocusId] = useState<number | null>(null)

  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const headingRefs = useRef(new Map<number, HTMLHeadingElement>())
  const resetHeadingRef = useRef<HTMLHeadingElement>(null)

  // 받은 첫 질문은 바로 지웁니다 (뒤로가기·새로고침 시 자동 재전송 방지)
  useEffect(() => {
    if (location.state) navigate(`${location.pathname}${location.search}`, { replace: true, state: null })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // "보낼 것"이 생기면 한 번 요청. 페이지를 떠나면 취소
  useEffect(() => {
    if (!pending) return
    const controller = new AbortController()
    let timedOut = false
    const timer = window.setTimeout(() => {
      timedOut = true
      controller.abort()
      setSend({ status: 'error', text: pending.text, message: '답을 기다리는 시간이 너무 길어요. 다시 시도해 주세요.', retryable: true })
      setPending(null)
    }, TIMEOUT_MS)

    chat({ question: pending.text, sessionId: sessionRef.current, region }, { signal: controller.signal })
      .then((reply) => {
        if (reply.sessionId) {
          sessionRef.current = reply.sessionId
          saveSessionId(reply.sessionId)
          setMemoryOff(false)
        } else {
          setMemoryOff(true)
        }
        const id = nextId.current++
        setMessages((prev) => [...prev, { id, role: 'assistant', reply }])
        setFocusId(id)
        setSend({ status: 'idle' })
        setPending(null)
      })
      .catch((err: unknown) => {
        if (isAbortError(err) || timedOut) return
        const error =
          err instanceof ApiError
            ? { message: err.message, retryable: err.retryable }
            : { message: '답을 가져오지 못했어요. 잠시 후 다시 시도해 주세요.', retryable: true }
        setSend({ status: 'error', text: pending.text, ...error })
        setPending(null)
      })
      .finally(() => window.clearTimeout(timer))

    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [pending])

  // 새 답변이 화면에 붙은 뒤 그 제목으로 포커스 이동 (화면 읽기 프로그램·키보드 사용자)
  useEffect(() => {
    if (focusId === null) return
    const el = headingRefs.current.get(focusId)
    el?.focus()
    setFocusId(null)
  }, [focusId, messages])

  const sending = send.status === 'sending'

  function submitText(text: string) {
    const trimmed = text.trim()
    if (!trimmed) {
      setDraftError('궁금한 내용을 적어 주세요.')
      return
    }
    if (trimmed.length > QUESTION_MAX_LENGTH) {
      setDraftError(`${QUESTION_MAX_LENGTH}자까지 적을 수 있어요. 지금 ${trimmed.length}자예요.`)
      return
    }
    if (sending) return
    setDraftError(null)
    setDraft('')
    setMessages((prev) => [...prev, { id: nextId.current++, role: 'user', text: trimmed }])
    setSend({ status: 'sending' })
    setPending({ id: nextId.current++, text: trimmed })
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault()
    submitText(draft)
  }

  /** 실패한 메시지를 같은 내용으로 다시 보냄 (메시지 목록에는 이미 있음) */
  function retry() {
    if (send.status !== 'error') return
    const text = send.text
    setSend({ status: 'sending' })
    setPending({ id: nextId.current++, text })
  }

  function resetConversation() {
    sessionRef.current = null
    clearSessionId()
    setMessages([])
    setSend({ status: 'idle' })
    setPending(null)
    setDraft('')
    setDraftError(null)
    setMemoryOff(false)
    setConfirmReset(false)
    textareaRef.current?.focus()
  }

  // 추가 질문이 있는 경우에만 Agent의 선택지를 표시한다. 임의의 예시 선택지를 사용하지 않는다.
  const last = messages[messages.length - 1]
  const followUp = last?.role === 'assistant' ? last.reply.followUp : null
  const showChips = Boolean(followUp && !sending)

  const draftLength = draft.trim().length
  const describedBy = ['chat-help', draftError ? 'chat-error' : null].filter(Boolean).join(' ')

  return (
    <>
      <Header title="복지 상담" showBack />
      <main className="px-[1.125rem] pb-10 pt-4">
        {hadPreviousSession && messages.length === 0 && (
          <p role="status" className="mt-4 rounded-card border border-line bg-surface p-4 text-base leading-relaxed">
            이전 대화 내용은 화면에서 사라졌어요. 계속 질문하시면 서버가 기억하는 범위에서 이어서 답해 드려요. 처음부터 하시려면 아래 "새로 시작"을 눌러 주세요.
          </p>
        )}

        {messages.length === 0 && !hadPreviousSession && (
          <p className="mt-4 text-lg leading-relaxed">궁금한 복지를 아래에 적어 주세요. 답을 보시고 이어서 더 물어보실 수 있어요.</p>
        )}

        {/* 대화 목록. 새 답변은 aria-live 로 알리고 제목으로 포커스를 옮깁니다 */}
        <ol aria-live="polite" aria-label="대화" className="mt-4 flex flex-col gap-3">
          {messages.map((m) =>
            m.role === 'user' ? (
              <li key={m.id} className="flex justify-end">
                <p className="max-w-[85%] rounded-card rounded-br-md border border-line bg-surface px-4 py-3 text-lg leading-relaxed shadow-sm">
                  <span className="sr-only">내 말: </span>
                  {m.text}
                </p>
              </li>
            ) : m.reply.followUp ? null : (
              <li key={m.id} className="scroll-mt-24">
                <AssistantCard
                  reply={m.reply}
                  headingRef={(el) => {
                    if (el) headingRefs.current.set(m.id, el)
                    else headingRefs.current.delete(m.id)
                  }}
                />
              </li>
            ),
          )}
          {sending && (
            <li>
              <div role="status" className="rounded-card border border-line bg-surface p-5 text-center">
                <p className="text-2xl" aria-hidden>
                  🔎
                </p>
                <p className="mt-2 text-lg font-bold">답을 찾고 있어요, 잠시만요…</p>
                <p className="mt-1 text-base text-muted">보통 몇 초면 돼요</p>
              </div>
            </li>
          )}
        </ol>

        {send.status === 'error' && (
          <div className="mt-3">
            <ErrorBox message={send.message} retryable={send.retryable} onRetry={retry} alternative={{ label: '홈으로 가기', to: '/' }} />
            {send.retryable && <p className="mt-1 text-sm text-muted">다시 시도하면 같은 내용이 대화에 두 번 남을 수 있어요.</p>}
          </div>
        )}

        {showChips && (
          <div className="mt-3">
            <SituationChips
              followUp={followUp!}
              disabled={sending}
              onPick={submitText}
            />
          </div>
        )}

        {/* 이어서 입력 */}
        <form onSubmit={handleSubmit} className="mt-4 rounded-card border border-line bg-surface p-5 shadow-sm">
          <label htmlFor="chat-input" className="block text-lg font-bold leading-snug">
            이어서 말씀해 주세요
          </label>
          <p id="chat-help" className="mt-1 text-sm text-muted">
            앞에서 하신 말씀에 이어서 답해 드려요. 이름·전화번호·주민번호는 적지 마세요.
          </p>
          <textarea
            id="chat-input"
            ref={textareaRef}
            value={draft}
            onChange={(e) => {
              setDraft(e.target.value)
              if (draftError) setDraftError(null)
            }}
            rows={3}
            disabled={sending}
            aria-describedby={describedBy}
            aria-invalid={draftError ? true : undefined}
            placeholder="예: 돈이 없어서요"
            className="mt-2 w-full rounded-button border-2 border-line bg-surface p-3 text-lg leading-relaxed focus:border-primary disabled:bg-surface-2"
          />
          <div className="mt-1 flex items-center justify-between text-sm text-muted">
            <span>
              {draftLength}/{QUESTION_MAX_LENGTH}자
            </span>
          </div>
          {draftError && (
            <p id="chat-error" role="alert" className="mt-1 text-base font-semibold text-danger">
              {draftError}
            </p>
          )}
          <BigButton type="submit" disabled={sending} className="mt-3 min-h-16! text-xl">
            이어서 보내기
          </BigButton>
          {memoryOff && (
            <p role="status" className="mt-2 text-sm leading-snug text-accent-dark">
              지금은 서버가 대화를 기억하지 않아요. 앞서 말씀하신 내용은 다시 적어 주셔야 해요.
            </p>
          )}
        </form>

        {/* 새로 시작 */}
        <div className="mt-3">
          {confirmReset ? (
            <div role="group" aria-labelledby="reset-heading" className="rounded-card border border-line bg-surface p-4">
              <p id="reset-heading" ref={resetHeadingRef} tabIndex={-1} className="text-lg font-bold outline-none">
                지금까지 대화를 지우고 새로 시작할까요?
              </p>
              <p className="mt-1 text-sm text-muted">화면의 대화가 지워지고 앞서 말씀하신 내용은 이어지지 않아요.</p>
              <div className="mt-3 flex flex-col gap-2">
                <BigButton onClick={resetConversation}>네, 새로 시작할게요</BigButton>
                <BigButton variant="secondary" onClick={() => setConfirmReset(false)}>
                  아니요, 계속할게요
                </BigButton>
              </div>
            </div>
          ) : (
            <button
              type="button"
              disabled={sending || messages.length === 0}
              onClick={() => {
                setConfirmReset(true)
                window.setTimeout(() => resetHeadingRef.current?.focus(), 0)
              }}
              className="min-h-12 w-full rounded-button border border-line bg-surface px-4 py-2 text-base font-semibold text-ink hover:bg-surface-2 disabled:opacity-50"
            >
              🗑 새로 시작
            </button>
          )}
        </div>

        {/* 전화 */}
        <section className="mt-6 rounded-card border-2 border-accent bg-surface p-4 text-center">
          <p className="text-base text-muted">전화로 물어보고 싶으시면</p>
          <div className="mt-3">
            <PhoneButton contact={{ label: '보건복지상담센터', tel: '129' }} />
          </div>
        </section>
      </main>
    </>
  )
}
