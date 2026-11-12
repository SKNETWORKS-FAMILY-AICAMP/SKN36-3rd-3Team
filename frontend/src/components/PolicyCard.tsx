/**
 * 검색 결과의 정책 카드. 카드 전체가 상세 페이지로 가는 링크입니다.
 * (전화 버튼은 상세 페이지에 있어서 링크가 겹치지 않습니다.)
 * snippet은 서버(지금은 mock)가 "누가 받을 수 있나" 요약이 있으면 그것을, 없으면 원문 한 문장을 보냅니다.
 */
import { Link } from 'react-router-dom'
import type { PolicyItem } from '../types/view'
import { BadgeList } from './Badge'

export default function PolicyCard({ item, rank }: { item: PolicyItem; rank: number }) {
  const regionText = item.sidoName ? `${item.sidoName}${item.sigunguName ? ` ${item.sigunguName}` : ' 전체'}` : '전국'
  return (
    <Link
      to={`/policy/${encodeURIComponent(item.policyId)}`}
      className="block rounded-card border border-line bg-surface p-4 shadow-sm hover:border-primary-dark"
    >
      <div className="flex items-start gap-3">
        <span aria-hidden className="flex size-9 shrink-0 items-center justify-center rounded-full bg-primary text-lg font-bold text-on-primary">
          {rank}
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="text-lg font-bold leading-snug">{item.title}</h3>
          <p className="mt-0.5 text-sm text-muted">📍 {regionText}</p>
        </div>
      </div>
      <p className="mt-3 text-base leading-relaxed text-ink">{item.snippet}</p>
      <div className="mt-3">
        <BadgeList badges={item.badges} />
      </div>
      <p className="mt-3 text-right text-base font-semibold text-primary-dark">자세히 보기 →</p>
    </Link>
  )
}
