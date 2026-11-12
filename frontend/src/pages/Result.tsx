/**
 * 결과 화면. URL(/result?q=&scope=...)에서 검색 조건을 읽어 요청하고 답변을 보여 줍니다.
 *
 * 요청 상태는 useReducer 하나로 관리합니다: idle → loading → success | error
 * - 요청마다 번호(requestId)를 붙여, 늦게 도착한 이전 요청의 응답은 무시합니다.
 * - 페이지를 떠나거나 조건이 바뀌면 AbortController로 요청을 취소합니다. 취소는 오류가 아닙니다.
 * - 30초가 지나면 "시간 초과" 오류를 보여 주고 요청을 중단합니다. 이때 생기는 AbortError가
 *   이미 표시한 시간 초과 오류를 덮어쓰지 않게 requestId로 거릅니다.
 *
 * 화면 상태(answered / partial / empty)는 응답 내용으로 계산합니다.
 */
import { useEffect, useReducer } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ask, isAbortError } from '../api'
import ErrorBox from '../components/ErrorBox'
import GuidelineCard from '../components/GuidelineCard'
import Header from '../components/Header'
import PhoneButton from '../components/PhoneButton'
import PolicyCard from '../components/PolicyCard'
import { formatRegion, parseSearchParams, type SearchQuery } from '../lib/searchParams'
import { ApiError, type AskResult } from '../types/view'

const TIMEOUT_MS = 120_000

type State =
  | { status: 'idle'; requestId: number }
  | { status: 'loading'; requestId: number }
  | { status: 'success'; requestId: number; data: AskResult }
  | { status: 'error'; requestId: number; error: { message: string; retryable: boolean } }

type Action =
  | { type: 'start'; requestId: number }
  | { type: 'success'; requestId: number; data: AskResult }
  | { type: 'error'; requestId: number; error: { message: string; retryable: boolean } }

function reducer(state: State, action: Action): State {
  // 지금 기다리는 요청이 아니면(이전 요청의 늦은 응답) 무시
  if (action.type !== 'start' && action.requestId !== state.requestId) return state
  switch (action.type) {
    case 'start':
      return { status: 'loading', requestId: action.requestId }
    case 'success':
      return { status: 'success', requestId: action.requestId, data: action.data }
    case 'error':
      return { status: 'error', requestId: action.requestId, error: action.error }
  }
}

let nextRequestId = 1

/** "질문 고치기"로 홈에 돌아갈 때 질문(q)과 개발용 dev 값만 가져갑니다 */
function editParams(params: URLSearchParams): URLSearchParams {
  const out = new URLSearchParams()
  const q = params.get('q')
  const dev = params.get('dev')
  if (q) out.set('q', q)
  if (dev) out.set('dev', dev)
  return out
}

export default function Result() {
  const [params] = useSearchParams()
  const parsed = parseSearchParams(params)
  const [state, dispatch] = useReducer(reducer, { status: 'idle', requestId: 0 })
  const [retryCount, retry] = useReducer((n: number) => n + 1, 0)

  const query: SearchQuery | null = parsed.ok ? parsed.value : null
  const queryKey = query ? JSON.stringify(query) : null

  useEffect(() => {
    if (!query) return
    const requestId = nextRequestId++
    const controller = new AbortController()
    let timedOut = false
    dispatch({ type: 'start', requestId })

    const timer = window.setTimeout(() => {
      timedOut = true
      dispatch({ type: 'error', requestId, error: { message: '답변을 기다리는 시간이 너무 길어요. 다시 시도해 주세요.', retryable: true } })
      controller.abort()
    }, TIMEOUT_MS)

    ask(query, { signal: controller.signal })
      .then((data) => dispatch({ type: 'success', requestId, data }))
      .catch((err: unknown) => {
        if (isAbortError(err)) return // 취소(페이지 이동·조건 변경·시간 초과 후 중단)는 오류 아님
        if (timedOut) return
        const error =
          err instanceof ApiError
            ? { message: err.message, retryable: err.retryable }
            : { message: '답변을 가져오지 못했어요. 잠시 후 다시 시도해 주세요.', retryable: true }
        dispatch({ type: 'error', requestId, error })
      })
      .finally(() => window.clearTimeout(timer))

    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
    // queryKey가 바뀔 때(새 검색)와 재시도 버튼을 눌렀을 때만 다시 요청
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [queryKey, retryCount])

  // URL이 잘못된 경우
  if (parsed.ok === false) {
    const message =
      parsed.reason === 'missing_question'
        ? '질문이 비어 있어요.'
        : parsed.reason === 'question_too_long'
          ? '질문이 너무 길어요. 300자 안으로 줄여 주세요.'
          : '지역 정보가 올바르지 않아요.'
    return (
      <>
        <Header title="검색 결과" showBack />
        <main className="px-[1.125rem] py-5">
          <ErrorBox message={message} retryable={false} alternative={{ label: '홈으로 가서 다시 질문하기', to: '/' }} />
        </main>
      </>
    )
  }

  const q = parsed.value

  return (
    <>
      <Header title="검색 결과" showBack />
      <main className="px-[1.125rem] pb-10 pt-4">
        {/* 내가 한 질문 */}
        <section className="rounded-card border border-line bg-surface p-4">
          <p className="text-sm font-semibold text-muted">📍 {formatRegion(q.region)}</p>
          <p className="mt-1 text-lg font-bold leading-snug">“{q.question}”</p>
          <Link to={`/?${editParams(params).toString()}`} className="mt-2 inline-block min-h-11 py-2 text-base font-semibold text-primary-dark underline">
            질문 고치기
          </Link>
        </section>

        {state.status === 'loading' && (
          <div role="status" aria-live="polite" className="mt-6 rounded-card border border-line bg-surface p-6 text-center">
            <p className="text-2xl" aria-hidden>
              🔎
            </p>
            <p className="mt-2 text-lg font-bold">찾고 있어요, 잠시만요…</p>
            <p className="mt-1 text-base text-muted">보통 몇 초면 돼요</p>
          </div>
        )}

        {state.status === 'error' && (
          <div className="mt-6">
            <ErrorBox
              message={state.error.message}
              retryable={state.error.retryable}
              onRetry={retry}
              alternative={{ label: '홈으로 가서 다시 질문하기', to: '/' }}
            />
          </div>
        )}

        {state.status === 'success' && <ResultBody data={state.data} />}
      </main>
    </>
  )
}

function ResultBody({ data }: { data: AskResult }) {
  const hasItems = data.items.length > 0
  const policies = data.items.filter((i) => i.kind === 'policy')
  const guidelines = data.items.filter((i) => i.kind === 'guideline')

  return (
    <div aria-live="polite">
      {/* 검색 범위 안내 (partial) */}
      {data.scopeNotice && (
        <p role="status" className="mt-4 rounded-card border border-accent/50 bg-accent-soft p-4 text-base font-semibold text-accent-dark">
          {data.scopeNotice.message}
        </p>
      )}

      {/* 답변 */}
      <section className="mt-4 rounded-card border border-primary/40 bg-primary-soft p-5">
        <p className="text-sm font-semibold text-primary-dark">답변</p>
        <p className="mt-2 whitespace-pre-line text-lg leading-relaxed">{data.answer}</p>
      </section>

      {/* 결과 없음 (empty) */}
      {!hasItems && data.fallback && (
        <section className="mt-4 rounded-card border border-line bg-surface p-5">
          <p className="text-lg font-bold">{data.fallback.message}</p>
          <div className="mt-4">
            <PhoneButton contact={{ label: '보건복지상담센터', tel: '129' }} />
          </div>
        </section>
      )}

      {/* 정책 카드 */}
      {policies.length > 0 && (
        <section className="mt-6">
          <h2 className="text-xl font-bold">관련 복지 {policies.length}개</h2>
          <p className="mt-1 text-sm text-muted">자동으로 찾은 결과라 꼭 확인이 필요해요. 카드를 누르면 자세히 볼 수 있어요.</p>
          <ul className="mt-3 flex flex-col gap-3">
            {policies.map((item, i) => (
              <li key={item.policyId}>
                <PolicyCard item={item} rank={i + 1} />
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* 승인된 안내서 */}
      {guidelines.length > 0 && (
        <section className="mt-6">
          <h2 className="text-xl font-bold">공식 안내서</h2>
          <ul className="mt-3 flex flex-col gap-3">
            {guidelines.map((item) => (
              <li key={`${item.documentId}-${item.pageStart}`}>
                <GuidelineCard item={item} />
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* 검토 중 참고자료 (접힘) */}
      {data.referenceCandidates.length > 0 && (
        <details className="mt-6 rounded-card border border-line bg-surface p-4">
          <summary className="min-h-11 cursor-pointer text-lg font-bold">검토 중인 참고자료 {data.referenceCandidates.length}개</summary>
          <ul className="mt-3 flex flex-col gap-3">
            {data.referenceCandidates.map((item) => (
              <li key={`${item.documentId}-${item.pageStart}`}>
                <GuidelineCard item={item} />
              </li>
            ))}
          </ul>
        </details>
      )}

      {hasItems && (
        <section className="mt-8 rounded-card border-2 border-accent bg-surface p-4 text-center">
          <p className="text-base text-muted">더 궁금하시면 상담원과 통화하세요</p>
          <div className="mt-3">
            <PhoneButton contact={{ label: '보건복지상담센터', tel: '129' }} />
          </div>
        </section>
      )}
    </div>
  )
}
