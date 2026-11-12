/** LLM이 제시한 추가 질문을 제목으로 보여주고, 선택한 문장을 그대로 채팅에 전송한다. */
import type { FollowUp } from '../types/view'

type Props = {
  followUp: FollowUp
  disabled: boolean
  onPick: (text: string) => void
}

export default function SituationChips({ followUp, disabled, onPick }: Props) {
  return (
    <section aria-labelledby="situation-heading" className="rounded-card border-2 border-accent bg-surface p-4">
      <h3 id="situation-heading" className="text-xl font-bold leading-snug">
        {followUp.question}
      </h3>
      <p className="mt-1 text-base leading-snug text-muted">
        아래 선택지를 누르면 바로 보낼 수 있어요.
      </p>
      <ul className="mt-3 flex flex-col gap-2">
        {followUp.choices.map((item) => (
          <li key={item.id}>
            <button
              type="button"
              disabled={disabled}
              onClick={() => onPick(item.label)}
              className="flex min-h-14 w-full items-center gap-3 rounded-button border-2 border-primary bg-surface px-4 py-3 text-left text-lg font-bold leading-snug text-primary-dark hover:bg-primary-soft disabled:opacity-60"
            >
              <span aria-hidden className="min-w-6 text-center">{item.id}.</span>
              <span>{item.label}</span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}
