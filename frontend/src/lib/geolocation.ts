/**
 * 브라우저 위치(Geolocation) 한 번 조회.
 *
 * - 사용자가 버튼을 눌렀을 때만 부릅니다. 첫 방문에 자동으로 권한을 묻지 않고, 계속 추적(watchPosition)하지 않습니다.
 * - 좌표는 소수점 3자리(약 100m)로 줄여서 돌려줍니다. 지역(시·군·구)을 알아내는 데는 충분하고,
 *   정확한 집 위치를 서버에 보내지 않기 위해서입니다. 좌표를 저장·기록하지 않습니다.
 * - 실패 이유를 화면 문구로 바꾸기 쉽게 reason으로 구분합니다.
 *   unsupported: 브라우저가 위치 기능 없음 / insecure: http 주소라 위치 기능 사용 불가(https 필요)
 *   denied: 권한 거절 / unavailable: 위치를 알 수 없음 / timeout: 시간 초과
 */

export type Coords = { latitude: number; longitude: number }

export type GeoReason = 'unsupported' | 'insecure' | 'denied' | 'unavailable' | 'timeout'

export class GeoError extends Error {
  reason: GeoReason
  constructor(reason: GeoReason, message: string) {
    super(message)
    this.name = 'GeoError'
    this.reason = reason
  }
}

export const GEO_MESSAGES: Record<GeoReason, string> = {
  unsupported: '이 브라우저에서는 위치 찾기를 쓸 수 없어요. 지역을 직접 선택해 주세요.',
  insecure: '이 주소(http)에서는 위치 찾기를 쓸 수 없어요. 지역을 직접 선택해 주세요.',
  denied: '위치 권한이 꺼져 있어요. 휴대폰 설정에서 허용하거나, 지역을 직접 선택해 주세요.',
  unavailable: '지금 위치를 확인하지 못했어요. 지역을 직접 선택해 주세요.',
  timeout: '위치 확인이 너무 오래 걸려요. 지역을 직접 선택해 주세요.',
}

const TIMEOUT_MS = 10_000

function round3(n: number): number {
  return Math.round(n * 1000) / 1000
}

export function getCurrentCoords(signal?: AbortSignal): Promise<Coords> {
  return new Promise((resolve, reject) => {
    if (typeof navigator === 'undefined' || !('geolocation' in navigator)) {
      return reject(new GeoError('unsupported', GEO_MESSAGES.unsupported))
    }
    if (typeof window !== 'undefined' && window.isSecureContext === false) {
      return reject(new GeoError('insecure', GEO_MESSAGES.insecure))
    }
    if (signal?.aborted) return reject(new DOMException('취소되었습니다.', 'AbortError'))

    let settled = false
    const onAbort = () => {
      if (settled) return
      settled = true
      reject(new DOMException('취소되었습니다.', 'AbortError'))
    }
    signal?.addEventListener('abort', onAbort, { once: true })

    navigator.geolocation.getCurrentPosition(
      (pos) => {
        if (settled) return
        settled = true
        signal?.removeEventListener('abort', onAbort)
        resolve({ latitude: round3(pos.coords.latitude), longitude: round3(pos.coords.longitude) })
      },
      (err) => {
        if (settled) return
        settled = true
        signal?.removeEventListener('abort', onAbort)
        const reason: GeoReason = err.code === err.PERMISSION_DENIED ? 'denied' : err.code === err.TIMEOUT ? 'timeout' : 'unavailable'
        reject(new GeoError(reason, GEO_MESSAGES[reason]))
      },
      { enableHighAccuracy: false, timeout: TIMEOUT_MS, maximumAge: 60_000 },
    )
  })
}
