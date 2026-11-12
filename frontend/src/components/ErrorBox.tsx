/**
 * 오류 안내 상자.
 * - retryable(다시 시도하면 될 수 있는 오류)이면 "다시 시도" 버튼
 * - 아니면(잘못된 입력 등) "질문 고치기" / "홈으로"처럼 해결할 수 있는 행동을 보여 줍니다.
 */
import BigButton from './BigButton'

type Props = {
  title?: string
  message: string
  retryable: boolean
  onRetry?: () => void
  /** retryable=false일 때 대신 보여 줄 행동 */
  alternative?: { label: string; to: string }
}

export default function ErrorBox({ title = '문제가 생겼어요', message, retryable, onRetry, alternative }: Props) {
  return (
    <div role="alert" className="rounded-card border border-danger/40 bg-danger-soft p-4">
      <p className="text-lg font-bold text-danger">{title}</p>
      <p className="mt-1 text-base leading-relaxed text-ink">{message}</p>
      <div className="mt-4">
        {retryable && onRetry ? (
          <BigButton onClick={onRetry}>다시 시도</BigButton>
        ) : alternative ? (
          <BigButton to={alternative.to} variant="ghost">
            {alternative.label}
          </BigButton>
        ) : null}
      </div>
    </div>
  )
}
