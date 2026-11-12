/** 실제 위치 변환만 서버에 연결한다. 복지 질문·상세 mock은 기존대로 유지한다. */
import { ApiError, type LocatedRegion } from '../types/view'
import { getDevScenario } from './devScenario'
import { locateRegion as mockLocateRegion, type RequestOptions } from './mock'

const unavailable = () => new ApiError('upstream_unavailable', '지역을 찾지 못했어요. 잠시 후 다시 시도하거나 지역을 직접 선택해 주세요.', true)

export async function locateRegion(
  coords: { latitude: number; longitude: number },
  options: RequestOptions = {},
): Promise<LocatedRegion> {
  if (getDevScenario() === 'locate_ok') return mockLocateRegion(coords, options)
  const controller = new AbortController()
  const cancel = () => controller.abort()
  if (options.signal?.aborted) throw new DOMException('요청이 취소되었습니다.', 'AbortError')
  options.signal?.addEventListener('abort', cancel, { once: true })
  const timer = window.setTimeout(cancel, 8000)
  try {
    const response = await fetch('/api/location/region', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(coords),
      signal: controller.signal,
    })
    const data: unknown = await response.json()
    if (typeof data !== 'object' || data === null) throw unavailable()
    const value = data as Record<string, unknown>
    if (!response.ok) {
      if (typeof value.code === 'string' && typeof value.message === 'string' && typeof value.retryable === 'boolean') {
        throw new ApiError(value.code, value.message, value.retryable)
      }
      throw unavailable()
    }
    if (typeof value.sido_name !== 'string' || !value.sido_name.trim()
      || (value.sigungu_name !== null && typeof value.sigungu_name !== 'string')
      || (value.region_code !== null && typeof value.region_code !== 'string')) throw unavailable()
    return { sidoName: value.sido_name, sigunguName: value.sigungu_name as string | null, regionCode: value.region_code as string | null }
  } catch (err) {
    if (options.signal?.aborted) throw new DOMException('요청이 취소되었습니다.', 'AbortError')
    if (err instanceof ApiError) throw err
    throw unavailable()
  } finally {
    window.clearTimeout(timer)
    options.signal?.removeEventListener('abort', cancel)
  }
}
