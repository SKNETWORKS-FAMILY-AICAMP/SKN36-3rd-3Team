/**
 * 음성 입출력 (브라우저 내장 Web Speech API). 새 패키지·서버 없이 동작합니다.
 *
 * - STT(말 → 글자): 크롬 등에 들어 있는 인식기를 씁니다. 크롬은 소리를 구글 서버로 보내 글자로 바꿉니다.
 *   우리 코드는 받은 글자를 입력창에 넘겨 주기만 합니다. 자동 전송하지 않습니다.
 * - TTS(글자 → 말): 기기에 깔린 한국어 목소리로 읽습니다. 한 번에 한 답변만 읽습니다.
 * - LLM 모델과는 무관합니다. 입력창 글자와 화면의 답변 글자만 다룹니다.
 */

/* ───────────── STT ───────────── */

// 브라우저마다 타입 정의가 달라 필요한 부분만 직접 적습니다.
type RecognitionAlternativeLike = { transcript: string }
type RecognitionResultLike = { isFinal: boolean; length: number; [index: number]: RecognitionAlternativeLike }
type RecognitionEventLike = { resultIndex: number; results: { length: number; [index: number]: RecognitionResultLike } }
type RecognitionErrorEventLike = { error: string }
type RecognitionLike = {
  lang: string
  interimResults: boolean
  continuous: boolean
  maxAlternatives: number
  onresult: ((event: RecognitionEventLike) => void) | null
  onerror: ((event: RecognitionErrorEventLike) => void) | null
  onend: (() => void) | null
  start(): void
  stop(): void
  abort(): void
}
type RecognitionConstructor = new () => RecognitionLike

function getRecognitionConstructor(): RecognitionConstructor | null {
  if (typeof window === 'undefined') return null
  const w = window as unknown as { SpeechRecognition?: RecognitionConstructor; webkitSpeechRecognition?: RecognitionConstructor }
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null
}

/** 이 브라우저에서 음성 인식을 쓸 수 있는지 */
export function isRecognitionSupported(): boolean {
  return getRecognitionConstructor() !== null
}

/** 마이크는 보안 연결(localhost 또는 https)에서만 동작합니다 */
export function isSecureForMicrophone(): boolean {
  return typeof window !== 'undefined' && window.isSecureContext
}

export type RecognitionErrorCode = 'not-allowed' | 'no-speech' | 'audio-capture' | 'network' | 'other'

function toErrorCode(raw: string): RecognitionErrorCode | null {
  if (raw === 'aborted') return null // 우리가 취소한 것. 오류가 아닙니다
  if (raw === 'not-allowed' || raw === 'service-not-allowed') return 'not-allowed'
  if (raw === 'no-speech' || raw === 'audio-capture' || raw === 'network') return raw
  return 'other'
}

export type RecognitionHandlers = {
  /** 아직 확정되지 않은 중간 결과. 입력창에 넣지 말고 표시만 합니다 */
  onInterim: (text: string) => void
  /** 확정된 문장. 한 번만 전달됩니다 */
  onFinal: (text: string) => void
  onError: (code: RecognitionErrorCode) => void
  /** 인식이 끝남 (정상 종료·오류 모두). abort() 뒤에는 부르지 않습니다 */
  onEnd: () => void
}

export type RecognitionSession = {
  /** 말하기 끝내기: 마지막 인식 결과까지 받습니다 */
  stop(): void
  /** 취소: 결과를 버립니다. 이후 늦게 도착한 결과도 전달하지 않습니다 */
  abort(): void
}

/* 듣기·읽기 공통 상태. 화면의 마이크·읽기 버튼이 함께 봅니다 */
const listeners = new Set<() => void>()
function notify() {
  listeners.forEach((listener) => listener())
}
export function subscribeSpeech(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

/** 마이크가 듣고 있는지. 듣는 동안에는 읽기를 시작하지 않습니다(스피커 소리가 다시 인식되지 않게) */
let recognitionActive = false
function setRecognitionActive(active: boolean) {
  if (recognitionActive === active) return
  recognitionActive = active
  notify()
}
export function getRecognitionActive(): boolean {
  return recognitionActive
}

/** 한국어 인식을 시작합니다. 시작하면서 읽고 있던 답변은 멈춥니다(스피커 소리를 다시 인식하지 않게). */
export function startRecognition(handlers: RecognitionHandlers): RecognitionSession {
  const Recognition = getRecognitionConstructor()
  if (!Recognition) throw new Error('speech recognition unsupported')
  stopSpeaking()

  const recognition = new Recognition()
  recognition.lang = 'ko-KR'
  recognition.interimResults = true
  recognition.continuous = false // 말을 멈추면 자동으로 끝납니다. 이어서 말하려면 다시 누릅니다
  recognition.maxAlternatives = 1

  let cancelled = false
  recognition.onresult = (event) => {
    if (cancelled) return
    let interim = ''
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const result = event.results[i]
      const text = result[0]?.transcript ?? ''
      if (result.isFinal) {
        const finalText = text.trim()
        if (finalText) handlers.onFinal(finalText)
      } else {
        interim += text
      }
    }
    handlers.onInterim(interim.trim())
  }
  recognition.onerror = (event) => {
    if (cancelled) return
    const code = toErrorCode(event.error)
    if (code) handlers.onError(code)
  }
  recognition.onend = () => {
    if (cancelled) return
    setRecognitionActive(false)
    handlers.onEnd()
  }

  recognition.start()
  setRecognitionActive(true)

  return {
    stop: () => {
      if (!cancelled) recognition.stop()
    },
    abort: () => {
      if (cancelled) return
      cancelled = true
      setRecognitionActive(false)
      recognition.onresult = null
      recognition.onerror = null
      recognition.onend = null
      try {
        recognition.abort()
      } catch {
        // 이미 끝난 경우 무시
      }
    },
  }
}

/**
 * 확정된 인식 문장을 기존 입력 뒤에 이어 붙입니다.
 * 제한 글자 수를 넘으면 null을 돌려줍니다(기존 입력을 지키고, 몰래 잘라 내지 않음).
 */
export function appendTranscript(current: string, addition: string, maxLength: number): string | null {
  const base = current.replace(/\s+$/, '')
  const next = base ? `${base} ${addition}` : addition
  return next.trim().length > maxLength ? null : next
}

/* ───────────── TTS ───────────── */

export function isSynthesisSupported(): boolean {
  return typeof window !== 'undefined' && 'speechSynthesis' in window && typeof window.SpeechSynthesisUtterance !== 'undefined'
}

/** 지금 읽고 있는 답변 id. 화면의 모든 읽기 버튼이 이 값을 함께 봅니다 */
let speakingId: string | null = null

function setSpeakingId(id: string | null) {
  if (speakingId === id) return
  speakingId = id
  notify()
}

export function getSpeakingId(): string | null {
  return speakingId
}

function pickKoreanVoice(voices: SpeechSynthesisVoice[]): SpeechSynthesisVoice | null {
  const korean = voices.filter((v) => v.lang.toLowerCase().replace('_', '-').startsWith('ko'))
  // 기기 안 목소리를 우선합니다(크롬의 온라인 목소리는 긴 글을 중간에 끊는 경우가 있음)
  return korean.find((v) => v.localService) ?? korean[0] ?? null
}

/**
 * 한국어 목소리를 찾습니다. 목록이 늦게(영어 목소리부터) 준비될 수 있어,
 * 한국어 목소리를 찾거나 제한 시간이 지날 때까지 기다립니다. 무한정 기다리지 않습니다.
 */
function loadKoreanVoice(timeoutMs = 3000): Promise<SpeechSynthesisVoice | null> {
  const synth = window.speechSynthesis
  const ready = pickKoreanVoice(synth.getVoices())
  if (ready) return Promise.resolve(ready)
  return new Promise((resolve) => {
    const finish = (voice: SpeechSynthesisVoice | null) => {
      window.clearTimeout(timer)
      synth.removeEventListener('voiceschanged', onChange)
      resolve(voice)
    }
    const onChange = () => {
      const voice = pickKoreanVoice(synth.getVoices())
      if (voice) finish(voice)
    }
    const timer = window.setTimeout(() => finish(pickKoreanVoice(synth.getVoices())), timeoutMs)
    synth.addEventListener('voiceschanged', onChange)
  })
}

/**
 * 읽기 전에 소리로 읽으면 어색한 마크다운 표시·주소·내부 ID만 정리합니다.
 * 본문 의미는 바꾸지 않습니다: 문장 중간의 >, *, = 같은 기호(예: "소득 > 기준액", "3 * 5")는 그대로 둡니다.
 */
export function cleanForSpeech(text: string): string {
  return text
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1') // [글자](주소) → 글자
    .replace(/https?:\/\/\S+/g, '') // 주소
    .replace(/\b(?:(?:local|central):[A-Za-z0-9_-]+|WLF\d+)/g, '') // 내부 정책 ID (영문·숫자까지만. 뒤에 붙은 한글·괄호는 지킴)
    .replace(/(\*\*|__)(?=\S)(.+?)(?<=\S)\1/g, '$2') // **굵게**, __굵게__
    .replace(/(?<![\w*])\*(?=\S)([^*\n]+?)(?<=\S)\*(?![\w*])/g, '$1') // *기울임* (띄어 쓴 "3 * 5"는 건드리지 않음)
    .replace(/`([^`\n]+)`/g, '$1') // `코드`
    .replace(/^\s{0,3}#{1,6}\s+/gm, '') // 줄 맨 앞 제목 표시
    .replace(/^\s{0,3}>\s?/gm, '') // 줄 맨 앞 인용 표시
    .replace(/^\s*[-*•·]\s+/gm, '') // 줄 맨 앞 목록 기호
    .replace(/[ \t]+/g, ' ')
    .replace(/\n{2,}/g, '\n')
    .trim()
}

/** 긴 글은 문장 단위로 나눠 읽습니다(한 번에 너무 길면 크롬이 중간에 멈추는 문제 방지) */
function splitForSpeech(text: string, maxChunk = 120): string[] {
  const sentences = text.split(/(?<=[.!?。])\s+|\n+/).map((s) => s.trim()).filter(Boolean)
  const chunks: string[] = []
  for (const sentence of sentences) {
    if (sentence.length <= maxChunk) {
      chunks.push(sentence)
      continue
    }
    for (let i = 0; i < sentence.length; i += maxChunk) chunks.push(sentence.slice(i, i + maxChunk))
  }
  return chunks
}

let speakToken = 0

export type SpeakResult = 'ok' | 'no-voice' | 'unsupported' | 'empty' | 'listening'

/** id 답변을 읽습니다. 다른 답변을 읽고 있었다면 먼저 멈춥니다. 마이크가 듣는 중이면 읽지 않습니다 */
export async function speak(id: string, text: string): Promise<SpeakResult> {
  if (!isSynthesisSupported()) return 'unsupported'
  if (recognitionActive) return 'listening'
  stopSpeaking()
  const chunks = splitForSpeech(cleanForSpeech(text))
  if (chunks.length === 0) return 'empty'

  const token = ++speakToken
  setSpeakingId(id)
  const voice = await loadKoreanVoice()
  if (token !== speakToken) return 'ok' // 기다리는 사이 멈추기·다른 읽기가 눌림
  if (!voice) {
    setSpeakingId(null)
    return 'no-voice'
  }

  chunks.forEach((chunk, index) => {
    const utterance = new SpeechSynthesisUtterance(chunk)
    utterance.lang = 'ko-KR'
    utterance.voice = voice
    utterance.rate = 0.9 // 조금 천천히
    const isLast = index === chunks.length - 1
    utterance.onend = () => {
      if (isLast && token === speakToken) setSpeakingId(null)
    }
    utterance.onerror = () => {
      if (token === speakToken) {
        window.speechSynthesis.cancel()
        setSpeakingId(null)
      }
    }
    window.speechSynthesis.speak(utterance)
  })
  return 'ok'
}

/** 모든 읽기를 멈춥니다. 모든 읽기 버튼이 "읽어 주기"로 돌아갑니다 */
export function stopSpeaking(): void {
  speakToken++
  if (isSynthesisSupported()) window.speechSynthesis.cancel()
  setSpeakingId(null)
}

// 탭을 닫거나 다른 사이트로 이동하면 읽기를 멈춥니다
if (typeof window !== 'undefined') window.addEventListener('pagehide', stopSpeaking)
