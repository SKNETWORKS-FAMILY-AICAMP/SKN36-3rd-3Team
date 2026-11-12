/**
 * 정책 상세 화면 (피그마 3:2 구조를 데이터 규칙에 맞게 재구성).
 *
 * 위에서부터:
 *   1. 요약 카드: 지역 · 제목 · 한 문장 요약 · 핵심 숫자(원문에 있을 때만) · 배지 · "확인 필요" 안내
 *   2. 한눈에 보기: 👤 누가 / 🎁 무엇을 / 📝 어떻게 — 서버가 검수해 내려 준 짧은 요약(highlights).
 *      없으면 "기관에 문의"로 대체합니다.
 *   3. 전화
 *   4. 자세한 내용(원문): 대상 · 선정 기준 · 지원 내용 · 신청 방법 전문. 기본은 접혀 있지만,
 *      "어떻게" 요약이 없고 신청 원문이 있으면 처음부터 펼쳐서 신청 방법을 숨기지 않습니다.
 *   5. 복지로 링크 · 관련 서식 · 안내서 근거 · 참고자료
 *
 * 피그마의 "월 최대 34만원 / 신청 3단계 / 준비물"은 데이터 규칙(원문 그대로, 기관 업무 단계를
 * 사용자 단계로 바꾸지 않음)에 따라 그대로 옮기지 않았습니다. 금액은 원문 숫자만 조건과 함께 보여 줍니다.
 */
import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { getPolicy, isAbortError } from '../api'
import { DEFAULT_CONTACT } from '../api/fixtures'
import { BadgeList } from '../components/Badge'
import BigButton from '../components/BigButton'
import ErrorBox from '../components/ErrorBox'
import GuidelineCard from '../components/GuidelineCard'
import Header from '../components/Header'
import PhoneButton from '../components/PhoneButton'
import { ApiError, type PolicyDetail as PolicyDetailType } from '../types/view'

type State =
  | { status: 'loading' }
  | { status: 'ready'; data: PolicyDetailType }
  | { status: 'not_found' }
  | { status: 'error'; message: string; retryable: boolean }

export default function PolicyDetail() {
  const { policyId = '' } = useParams()
  const [retryCount, setRetryCount] = useState(0)
  // 결과를 "어떤 요청(정책 id + 재시도 횟수)의 결과인지"와 함께 저장하고,
  // 현재 요청과 다르면 로딩 중으로 봅니다. (effect 안에서 setState를 부르지 않기 위한 방식)
  const requestKey = `${policyId}#${retryCount}`
  const [result, setResult] = useState<{ key: string; state: State } | null>(null)
  const state: State = result?.key === requestKey ? result.state : { status: 'loading' }

  useEffect(() => {
    const controller = new AbortController()
    const key = requestKey
    getPolicy(decodeURIComponent(policyId), { signal: controller.signal })
      .then((data) => setResult({ key, state: { status: 'ready', data } }))
      .catch((err: unknown) => {
        if (isAbortError(err)) return
        if (err instanceof ApiError && err.code === 'policy_not_found') return setResult({ key, state: { status: 'not_found' } })
        setResult({
          key,
          state: {
            status: 'error',
            message: err instanceof ApiError ? err.message : '정보를 가져오지 못했어요.',
            retryable: err instanceof ApiError ? err.retryable : true,
          },
        })
      })
    return () => controller.abort()
  }, [policyId, requestKey])

  const title = state.status === 'ready' ? state.data.title : '복지 상세'

  return (
    <>
      <Header title={title} showBack backFallback="/" />
      <main className="px-[1.125rem] pb-10 pt-4">
        {state.status === 'loading' && (
          <p role="status" className="py-10 text-center text-lg text-muted">
            불러오는 중…
          </p>
        )}

        {state.status === 'not_found' && (
          <ErrorBox
            title="정보를 찾지 못했어요"
            message="이 복지 정보는 지금 볼 수 없어요. 홈에서 다시 찾아보세요."
            retryable={false}
            alternative={{ label: '홈으로', to: '/' }}
          />
        )}

        {state.status === 'error' && (
          <ErrorBox message={state.message} retryable={state.retryable} onRetry={() => setRetryCount((n) => n + 1)} alternative={{ label: '홈으로', to: '/' }} />
        )}

        {state.status === 'ready' && <DetailBody data={state.data} />}
      </main>
    </>
  )
}

function DetailBody({ data }: { data: PolicyDetailType }) {
  const regionText = data.sidoName ? `${data.sidoName}${data.sigunguName ? ` ${data.sigunguName}` : ' 전체'}` : '전국 공통'
  const contacts = data.contacts.length > 0 ? data.contacts : [DEFAULT_CONTACT]
  const hasRawText = Boolean(data.targetText || data.selectionCriteriaText || data.benefitText || data.applicationText)
  // 신청 요약이 없는데 신청 원문은 있으면 원문을 처음부터 펼쳐 둡니다 (신청 방법을 숨기지 않기 위해)
  const openRawByDefault = data.highlights.how === null && Boolean(data.applicationText)

  return (
    <>
      {/* 1. 요약 카드 */}
      <section className="rounded-card border border-line bg-surface p-5 shadow-sm">
        <p className="text-sm font-semibold text-primary-dark">📍 {regionText}</p>
        <h2 className="mt-1 text-2xl font-bold leading-tight">{data.title}</h2>
        {data.summary && <p className="mt-2 text-lg leading-relaxed">{data.summary}</p>}
        {data.keyFigure && (
          <p className="mt-3 rounded-button bg-accent-soft p-3 text-2xl font-bold leading-snug text-accent-dark">
            {data.keyFigure}
            <span className="mt-1 block text-sm font-semibold text-muted">복지로 원문 기준</span>
          </p>
        )}
        <div className="mt-3">
          <BadgeList badges={data.badges} />
        </div>
        <p className="mt-3 rounded-button bg-primary-soft p-3 text-base font-semibold leading-relaxed text-primary-dark">
          ✅ 실제로 받으실 수 있는지는 아래 연락처나 주민센터에서 꼭 확인해 주세요.
        </p>
      </section>

      {/* 2. 한눈에 보기 */}
      <section className="mt-4 rounded-card border border-line bg-surface p-5">
        <h3 className="text-xl font-bold">한눈에 보기</h3>
        <dl className="mt-3 flex flex-col gap-3">
          <HighlightRow emoji="👤" label="누가" text={data.highlights.who} emptyText="대상 요약이 아직 없어요. 아래 원문이나 기관에서 확인해 주세요." />
          <HighlightRow emoji="🎁" label="무엇을" text={data.highlights.what} emptyText="지원 내용 요약이 아직 없어요. 아래 원문이나 기관에서 확인해 주세요." />
          <HighlightRow emoji="📝" label="어떻게" text={data.highlights.how} emptyText="신청 방법은 아래 원문이나 기관에서 확인해 주세요." />
        </dl>
      </section>

      {/* 3. 전화 */}
      <section className="mt-6">
        <h3 className="text-xl font-bold">전화로 물어보기</h3>
        {data.contactNote && <p className="mt-1 text-sm text-muted">기관 연락처 원문: {data.contactNote} (지역번호는 기관에 확인)</p>}
        <ul className="mt-3 flex flex-col gap-2">
          {contacts.map((c) => (
            <li key={c.tel}>
              <PhoneButton contact={c} />
            </li>
          ))}
          {data.contacts.length > 0 && !data.contacts.some((c) => c.tel === '129') && (
            <li>
              <PhoneButton contact={DEFAULT_CONTACT} />
            </li>
          )}
        </ul>
        {data.department && <p className="mt-2 text-sm text-muted">담당: {data.department}</p>}
      </section>

      {/* 4. 자세한 내용 (원문) */}
      {hasRawText && (
        <details className="mt-6 rounded-card border border-line bg-surface" open={openRawByDefault}>
          <summary className="flex min-h-12 cursor-pointer items-center justify-between px-5 py-3 text-lg font-bold">
            <span>📖 자세한 내용 (복지로 원문)</span>
            <span aria-hidden className="text-base font-semibold text-primary-dark">
              보기
            </span>
          </summary>
          <div className="flex flex-col gap-4 px-5 pb-5">
            <RawBlock title="누가 받을 수 있나요" text={data.targetText} />
            <RawBlock title="선정 기준" text={data.selectionCriteriaText} />
            <RawBlock title="어떤 지원인가요" text={data.benefitText} />
            <RawBlock title="어떻게 신청하나요" text={data.applicationText} />
          </div>
        </details>
      )}

      {/* 5. 출처·서식 */}
      <section className="mt-6 flex flex-col gap-2">
        {data.sourceUrl && (
          <BigButton to={data.sourceUrl} variant="ghost">
            🔗 복지로 공식 안내 보기 ↗
          </BigButton>
        )}
        {data.relatedForms.length > 0 && (
          <details className="rounded-card border border-line bg-surface">
            <summary className="flex min-h-12 cursor-pointer items-center justify-between px-5 py-3 text-lg font-bold">
              <span>📎 관련 서식 {data.relatedForms.length}개</span>
              <span aria-hidden className="text-base font-semibold text-primary-dark">
                보기
              </span>
            </summary>
            <ul className="flex flex-col gap-2 px-5 pb-5">
              {data.relatedForms.map((f) => (
                <li key={f.url}>
                  <a href={f.url} target="_blank" rel="noreferrer" className="block min-h-11 py-2 text-base font-semibold text-primary-dark underline">
                    {f.name} ↗
                  </a>
                </li>
              ))}
            </ul>
          </details>
        )}
      </section>

      {/* 안내서 근거 */}
      {data.sources.length > 0 && (
        <section className="mt-6">
          <h3 className="text-xl font-bold">공식 안내서 근거</h3>
          <ul className="mt-3 flex flex-col gap-3">
            {data.sources.map((g) => (
              <li key={`${g.documentId}-${g.pageStart}`}>
                <GuidelineCard item={g} />
              </li>
            ))}
          </ul>
        </section>
      )}
      {data.referenceCandidates.length > 0 && (
        <details className="mt-6 rounded-card border border-line bg-surface">
          <summary className="flex min-h-12 cursor-pointer items-center justify-between px-5 py-3 text-lg font-bold">
            <span>검토 중인 참고자료 {data.referenceCandidates.length}개</span>
            <span aria-hidden className="text-base font-semibold text-primary-dark">
              보기
            </span>
          </summary>
          <ul className="flex flex-col gap-3 px-5 pb-5">
            {data.referenceCandidates.map((g) => (
              <li key={`${g.documentId}-${g.pageStart}`}>
                <GuidelineCard item={g} />
              </li>
            ))}
          </ul>
        </details>
      )}

      <p className="mt-8 text-center text-sm text-muted">
        출처: 복지로(보건복지부) 공개 정보 ·{' '}
        <Link to="/" className="font-semibold text-primary-dark underline">
          홈으로
        </Link>
      </p>
    </>
  )
}

/** 한눈에 보기 한 줄. 글이 길면 자연스럽게 줄바꿈합니다(말줄임 없음) */
function HighlightRow({ emoji, label, text, emptyText }: { emoji: string; label: string; text: string | null; emptyText: string }) {
  return (
    <div className="flex gap-3">
      <dt className="flex w-20 shrink-0 items-start gap-1 text-base font-bold text-muted">
        <span aria-hidden>{emoji}</span>
        {label}
      </dt>
      {text ? (
        <dd className="m-0 flex-1 text-lg leading-relaxed">{text}</dd>
      ) : (
        <dd className="m-0 flex-1 rounded-button bg-accent-soft p-2 text-base font-semibold leading-snug text-accent-dark">{emptyText}</dd>
      )}
    </div>
  )
}

/** 원문 블록. 값이 없으면 통째로 숨깁니다 (원문 안에서 또 접지 않음) */
function RawBlock({ title, text }: { title: string; text: string | null }) {
  if (!text) return null
  return (
    <div>
      <h4 className="text-base font-bold text-muted">{title}</h4>
      <p className="mt-1 whitespace-pre-line text-lg leading-relaxed">{text}</p>
    </div>
  )
}
