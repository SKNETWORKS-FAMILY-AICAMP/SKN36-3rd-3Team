/**
 * 마이크 입력 상태를 관리하는 훅. Home·Chat이 함께 씁니다.
 *
 * - start(): 듣기 시작 / stop(): 말하기 끝내기(마지막 결과까지 받음) / abort(): 취소(결과 버림)
 * - 확정된 문장만 onFinal로 한 번 넘깁니다. 중간 결과(interim)는 표시용입니다.
 * - 화면을 떠나면 자동으로 취소합니다.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { isRecognitionSupported, isSecureForMicrophone, startRecognition, type RecognitionErrorCode, type RecognitionSession } from './speech'

export type SpeechInputStatus = 'idle' | 'listening' | 'stopping'

const ERROR_MESSAGES: Record<RecognitionErrorCode, string> = {
  'not-allowed': '마이크 사용이 막혀 있어요. 주소창 왼쪽의 자물쇠 표시를 눌러 마이크를 허용해 주세요. 글자로 적으셔도 돼요.',
  'no-speech': '목소리가 들리지 않았어요. 🎤를 누르고 다시 말씀해 주세요.',
  'audio-capture': '마이크를 찾지 못했어요. 마이크가 연결되어 있는지 확인해 주세요.',
  network: '인터넷 연결이 불안정해서 알아듣지 못했어요. 다시 말씀하시거나 글자로 적어 주세요.',
  other: '말씀을 알아듣지 못했어요. 다시 말씀하시거나 글자로 적어 주세요.',
}

export type SpeechInput = {
  /** 이 브라우저·연결에서 마이크를 쓸 수 있는지 */
  available: boolean
  /** 쓸 수 없다면 그 이유 (화면 안내용) */
  unavailableReason: string | null
  status: SpeechInputStatus
  /** 아직 확정되지 않은 말 (표시만) */
  interim: string
  error: string | null
  start: () => void
  stop: () => void
  abort: () => void
}

function getUnavailableReason(): string | null {
  if (!isRecognitionSupported()) return '이 브라우저에서는 음성으로 말하기를 쓸 수 없어요. 크롬에서 열어 주시거나 글자로 적어 주세요.'
  if (!isSecureForMicrophone()) return '보안 연결(https)이 아니라서 마이크를 쓸 수 없어요. 글자로 적어 주세요.'
  return null
}

export function useSpeechInput(onFinal: (text: string) => void): SpeechInput {
  const [unavailableReason] = useState(getUnavailableReason)
  const [status, setStatus] = useState<SpeechInputStatus>('idle')
  const [interim, setInterim] = useState('')
  const [error, setError] = useState<string | null>(null)
  const sessionRef = useRef<RecognitionSession | null>(null)
  const onFinalRef = useRef(onFinal)

  useEffect(() => {
    onFinalRef.current = onFinal
  })

  const abort = useCallback(() => {
    sessionRef.current?.abort()
    sessionRef.current = null
    setStatus('idle')
    setInterim('')
  }, [])

  // 화면을 떠나면 취소 (늦게 도착한 결과가 다른 화면에 들어가지 않게)
  useEffect(() => () => sessionRef.current?.abort(), [])

  const start = useCallback(() => {
    if (sessionRef.current || unavailableReason) return
    setError(null)
    setInterim('')
    try {
      sessionRef.current = startRecognition({
        onInterim: setInterim,
        onFinal: (text) => onFinalRef.current(text),
        onError: (code) => setError(ERROR_MESSAGES[code]),
        onEnd: () => {
          sessionRef.current = null
          setStatus('idle')
          setInterim('')
        },
      })
      setStatus('listening')
    } catch {
      sessionRef.current = null
      setStatus('idle')
      setError(ERROR_MESSAGES.other)
    }
  }, [unavailableReason])

  const stop = useCallback(() => {
    if (!sessionRef.current) return
    setStatus('stopping')
    sessionRef.current.stop()
  }, [])

  return { available: unavailableReason === null, unavailableReason, status, interim, error, start, stop, abort }
}
