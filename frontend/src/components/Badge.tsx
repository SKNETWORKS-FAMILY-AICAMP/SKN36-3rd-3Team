/**
 * 상태 배지. 서버(지금은 mock)가 준 문구와 색 톤을 그대로 보여 주기만 합니다.
 * 문구를 보고 동작을 바꾸지 않습니다. 색만으로 뜻을 전하지 않도록 문구가 항상 함께 있습니다.
 * tone 값(ok/warn/info)은 계약 그대로 두고, 여기서 색만 매핑합니다: ok=초록, warn=주황, info=회색
 */
import type { Badge as BadgeType } from '../types/view'

const toneClass = {
  ok: 'bg-primary-soft text-primary-dark',
  warn: 'bg-accent-soft text-accent-dark',
  info: 'bg-info-soft text-info',
} as const

export default function Badge({ badge }: { badge: BadgeType }) {
  return (
    <span className={`inline-block rounded-full px-2.5 py-1 text-sm font-semibold leading-tight ${toneClass[badge.tone]}`}>
      {badge.label}
    </span>
  )
}

export function BadgeList({ badges }: { badges: BadgeType[] }) {
  if (badges.length === 0) return null
  return (
    <ul className="flex flex-wrap gap-1.5" aria-label="상태">
      {badges.map((b) => (
        <li key={b.label}>
          <Badge badge={b} />
        </li>
      ))}
    </ul>
  )
}
