/**
 * 답변 읽어 주기 버튼. 누를 때만 읽고, 다시 누르면 멈춥니다.
 *
 * - 화면 전체에서 한 번에 한 답변만 읽습니다. 다른 답변을 읽기 시작하면 이 버튼은 "소리로 듣기"로 돌아옵니다.
 * - 마이크가 듣는 동안에는 누를 수 없습니다(읽는 소리가 다시 인식되지 않게).
 * - 이 버튼이 화면에서 사라지면(새로 시작·페이지 이동) 읽던 것을 멈춥니다.
 * - 브라우저가 읽기를 지원하지 않으면 버튼을 보여 주지 않습니다(글자 답변은 그대로).
 */
import { useEffect, useId, useState, useSyncExternalStore } from 'react'
import { getRecognitionActive, getSpeakingId, isSynthesisSupported, speak, stopSpeaking, subscribeSpeech } from '../lib/speech'

export default function SpeakButton({ text }: { text: string }) {
  const id = useId()
  const speakingId = useSyncExternalStore(subscribeSpeech, getSpeakingId, () => null)
  const listening = useSyncExternalStore(subscribeSpeech, getRecognitionActive, () => false)
  const speaking = speakingId === id
  const [notice, setNotice] = useState<string | null>(null)

  // 화면에서 사라질 때 이 답변을 읽고 있었다면 멈춤
  useEffect(
    () => () => {
      if (getSpeakingId() === id) stopSpeaking()
    },
    [id],
  )

  if (!isSynthesisSupported()) return null

  async function handleClick() {
    if (speaking) {
      stopSpeaking()
      return
    }
    setNotice(null)
    const result = await speak(id, text)
    if (result === 'no-voice') setNotice('이 기기에서 한국어 목소리를 찾지 못했어요. 잠시 후 다시 눌러 주세요.')
  }

  return (
    <div className="mt-3">
      <button
        type="button"
        onClick={handleClick}
        disabled={listening && !speaking}
        aria-pressed={speaking}
        className={`flex min-h-12 w-full items-center justify-center gap-2 rounded-button border-2 px-4 py-2 text-lg font-bold disabled:cursor-not-allowed disabled:opacity-50 ${
          speaking ? 'border-danger bg-surface text-danger' : 'border-primary bg-surface text-primary-dark hover:bg-primary-soft'
        }`}
      >
        <span aria-hidden>{speaking ? '⏹' : '🔊'}</span>
        {speaking ? '읽기 멈추기' : '소리로 듣기'}
      </button>
      {listening && !speaking && <p className="mt-1 text-sm text-muted">말씀을 듣는 동안에는 읽어 드릴 수 없어요.</p>}
      {notice && (
        <p role="status" className="mt-1 text-sm font-semibold text-accent-dark">
          {notice}
        </p>
      )}
    </div>
  )
}
