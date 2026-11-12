/** Frontend API boundary. Components import ONLY from this module. */
export { ask, chat, getPolicy, getRegions } from './http'
export { locateRegion } from './location'
export type { RequestOptions } from './http'

export function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError'
}
