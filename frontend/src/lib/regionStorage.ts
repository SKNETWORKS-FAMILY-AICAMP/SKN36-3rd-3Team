/**
 * 마지막으로 고른 지역을 기억합니다 (localStorage).
 * 어르신이 매번 지역을 고르지 않아도 되게 하려는 편의 기능이라, 실패해도 무시합니다.
 * 선택 창에 없는 시도(예: 예전에 고른 부산)가 저장돼 있으면 없는 것으로 봅니다.
 */
import { isServiceSido } from '../api/fixtures'
import type { RegionSelection } from '../types/view'

const KEY = 'welfare-ui.region'

export function loadRegion(): RegionSelection | null {
  try {
    const raw = window.localStorage.getItem(KEY)
    if (!raw) return null
    const parsed: unknown = JSON.parse(raw)
    if (typeof parsed !== 'object' || parsed === null || !('kind' in parsed)) return null
    const value = parsed as Record<string, unknown>
    if (value.kind === 'nationwide') return { kind: 'nationwide' }
    if (value.kind === 'region' && typeof value.sidoName === 'string' && isServiceSido(value.sidoName)) {
      return { kind: 'region', sidoName: value.sidoName, sigunguName: typeof value.sigunguName === 'string' ? value.sigunguName : null }
    }
    return null
  } catch {
    return null
  }
}

export function saveRegion(region: RegionSelection): void {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(region))
  } catch {
    // 무시
  }
}
