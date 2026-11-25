/** Frontend API boundary. Components import ONLY from this module. */
import { chat as httpChat } from './http'
import { chat as mockChat } from './mock'

export { ask, getPolicy, getRegions } from './http'
export { locateRegion } from './location'
export type { RequestOptions } from './http'

/**
 * 개발 모드 전용: `npm run dev:mock`(VITE_USE_MOCK=true)으로 켜면 대화 답변을 가짜 답변(mock)으로 받습니다.
 * 서버·LLM 없이 화면과 "소리로 듣기"를 확인하기 위한 것입니다.
 * 배포 빌드(import.meta.env.DEV=false)에서는 항상 실제 서버를 씁니다.
 */
const useMockChat = import.meta.env.DEV && import.meta.env.VITE_USE_MOCK === 'true'

export const chat: typeof httpChat = useMockChat ? (input, options) => mockChat(input, options) : httpChat

export function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError'
}
