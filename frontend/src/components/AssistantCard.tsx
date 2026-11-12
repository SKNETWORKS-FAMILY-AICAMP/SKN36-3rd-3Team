/**
 * 대화 화면의 답변 카드 1개 (서버 답변 1회분).
 *
 * answer_status 에 따라 모양이 다릅니다:
 * - success        초록 답변 + 참고한 자료 목록
 * - no_evidence    되묻기 답변. 상황 버튼(SituationChips)은 부모(Chat)가 이 카드 아래에 붙입니다
 * - safety_response 긴급: 빨간 테두리, 안전 안내를 크게, 112·119 전화 버튼. 상황 버튼 없음
 * - error          서버가 답을 만들지 못함 (다시 시도는 부모가 처리)
 * safety_status 가 distress 면 답변 위에 공감 띠를 한 줄 더 보여 줍니다 (answer_status 와 별개 축).
 *
 * - 제목(h2)에 tabIndex=-1 을 둬서 새 답변이 오면 부모가 여기로 포커스를 옮깁니다.
 * - 참고 자료 링크는 http/https 만 링크로 만들고, 그 밖은 글자로만 보여 줍니다.
 */
import type { ChatReply, ChatSource } from '../types/view'
import PhoneButton from './PhoneButton'

type Props = {
  reply: ChatReply
  /** 포커스를 받을 제목에 부모가 ref 를 줍니다 */
  headingRef?: (el: HTMLHeadingElement | null) => void
}

function isHttpUrl(url: string | null): url is string {
  return url !== null && /^https?:\/\//i.test(url)
}

function SourceItem({ source }: { source: ChatSource }) {
  const kind = source.sourceType === 'guideline' ? '공식 안내서' : '복지 정책'
  const pages =
    source.sourceType === 'guideline' && source.pageStart !== null
      ? ` · p.${source.pageStart}${source.pageEnd !== null && source.pageEnd !== source.pageStart ? `~${source.pageEnd}` : ''}`
      : ''
  return (
    <li className="rounded-button border border-line-soft bg-surface-2 px-3 py-2 text-base leading-snug">
      <span className="mr-2 rounded-md bg-info-soft px-2 py-0.5 text-sm font-semibold text-info">{kind}</span>
      {isHttpUrl(source.sourceUrl) ? (
        <a href={source.sourceUrl} target="_blank" rel="noopener noreferrer" className="font-semibold text-primary-dark underline">
          {source.title}
          <span className="sr-only"> (새 창에서 열림)</span>
        </a>
      ) : (
        <span className="font-semibold">{source.title}</span>
      )}
      {pages && <span className="text-muted">{pages}</span>}
    </li>
  )
}

export default function AssistantCard({ reply, headingRef }: Props) {
  if (reply.answerStatus === 'safety_response') {
    return (
      <section className="rounded-card border-[3px] border-danger bg-surface p-5 shadow-sm">
        <h2 ref={headingRef} tabIndex={-1} className="text-xl font-bold text-danger outline-none">
          🚨 먼저 안전이 중요해요
        </h2>
        <p className="mt-2 text-lg font-semibold leading-relaxed">{reply.answer}</p>
        <div className="mt-4 flex flex-col gap-2">
          <PhoneButton contact={{ label: '긴급 구조', tel: '119' }} />
          <PhoneButton contact={{ label: '경찰', tel: '112' }} />
        </div>
        <p className="mt-3 text-base leading-relaxed text-muted">복지 상담이 필요하시면 129(보건복지상담센터)로도 전화하실 수 있어요.</p>
      </section>
    )
  }

  const isNoEvidence = reply.answerStatus === 'no_evidence'
  const isError = reply.answerStatus === 'error'
  const tone = isError ? 'border-danger/40 bg-danger-soft' : isNoEvidence ? 'border-accent/60 bg-accent-soft' : 'border-primary/40 bg-primary-soft'
  const label = isError ? '답을 만들지 못했어요' : isNoEvidence ? '조금만 더 알려 주세요' : '답변'
  const labelColor = isError ? 'text-danger' : isNoEvidence ? 'text-accent-dark' : 'text-primary-dark'

  return (
    <section className={`rounded-card border ${tone} p-5`}>
      {reply.safetyStatus === 'distress' && (
        <p className="mb-3 rounded-button bg-surface px-3 py-2 text-base font-semibold leading-snug text-ink">
          🤝 많이 힘드셨겠어요. 혼자 애쓰지 않으셔도 돼요. 아래 안내와 함께 129 상담도 받으실 수 있어요.
        </p>
      )}
      <h2 ref={headingRef} tabIndex={-1} className={`text-sm font-semibold outline-none ${labelColor}`}>
        {label}
      </h2>
      <p className="mt-2 whitespace-pre-line text-lg leading-relaxed">{reply.answer}</p>

      {reply.sources.length > 0 && (
        <div className="mt-4">
          <p className="text-base font-bold">참고한 자료 {reply.sources.length}개</p>
          <p className="mt-0.5 text-sm text-muted">자동으로 찾은 자료라 꼭 확인이 필요해요. 신청 자격은 기관에서 확인해 주세요.</p>
          <ul className="mt-2 flex flex-col gap-2">
            {reply.sources.map((s, i) => (
              <SourceItem key={`${s.parentId ?? s.title}-${i}`} source={s} />
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}
