/**
 * 마이크 버튼과 음성 입력 안내 줄. 상태는 useSpeechInput 훅이 관리합니다.
 *
 * - MicButton: 🎤(듣기 시작) ↔ ⏹(말하기 끝내기). type="button"이라 폼을 보내지 않습니다.
 * - SpeechStatus: 듣는 중·중간 결과·오류·미지원 안내를 보여 줍니다(화면 읽기 프로그램에도 알림).
 * 인식한 글자는 입력창에만 들어가고 자동으로 보내지 않습니다.
 */
import type { SpeechInput } from '../lib/useSpeechInput'

type MicButtonProps = {
  speech: SpeechInput
  disabled?: boolean
  className?: string
}

export default function MicButton({ speech, disabled = false, className = '' }: MicButtonProps) {
  const listening = speech.status === 'listening'
  const stopping = speech.status === 'stopping'
  const label = !speech.available
    ? '음성으로 말하기 (이 환경에서는 쓸 수 없어요)'
    : listening
      ? '말하기 끝내기'
      : stopping
        ? '알아듣는 중'
        : '음성으로 말하기'

  return (
    <button
      type="button"
      onClick={listening ? speech.stop : speech.start}
      disabled={disabled || !speech.available || stopping}
      aria-label={label}
      title={label}
      className={`flex w-16 shrink-0 items-center justify-center rounded-button border-2 text-3xl disabled:cursor-not-allowed disabled:opacity-50 ${
        listening ? 'border-danger bg-danger-soft' : 'border-primary bg-surface hover:bg-primary-soft'
      } ${className}`}
    >
      <span aria-hidden>{listening ? '⏹' : stopping ? '⏳' : '🎤'}</span>
    </button>
  )
}

export function SpeechStatus({ speech }: { speech: SpeechInput }) {
  return (
    <div role="status" aria-live="polite" className="mt-1 text-base leading-snug">
      {!speech.available && <p className="text-sm text-muted">{speech.unavailableReason}</p>}
      {speech.status === 'listening' && (
        <p className="font-semibold text-danger">
          🔴 듣고 있어요. 말씀을 마치시면 ⏹를 눌러 주세요.
          {speech.interim && <span className="mt-1 block font-normal text-ink">“{speech.interim}”</span>}
        </p>
      )}
      {speech.status === 'stopping' && <p className="font-semibold text-muted">알아듣는 중이에요…</p>}
      {speech.error && speech.status === 'idle' && <p className="font-semibold text-accent-dark">{speech.error}</p>}
    </div>
  )
}
