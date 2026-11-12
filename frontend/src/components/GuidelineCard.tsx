/**
 * 공식 안내서(PDF) 결과 카드. 상세 페이지가 없어서 링크가 아닙니다.
 * 문서명과 쪽 범위를 보여 주고, 검토 중인 자료는 그렇게 표시합니다.
 */
import type { GuidelineItem } from '../types/view'
import { BadgeList } from './Badge'

export default function GuidelineCard({ item }: { item: GuidelineItem }) {
  const pages = item.pageExact && item.pageStart === item.pageEnd ? `p.${item.pageStart}` : `p.${item.pageStart}~${item.pageEnd}에 수록`
  return (
    <article className="rounded-card border border-line bg-surface p-4">
      <p className="text-sm font-semibold text-muted">📄 공식 안내서</p>
      <h3 className="mt-1 text-lg font-bold leading-snug">{item.documentTitle}</h3>
      <p className="text-sm text-muted">
        {item.sectionTitle ? `${item.sectionTitle} · ` : ''}
        {pages}
      </p>
      <p className="mt-2 text-base leading-relaxed">{item.snippet}</p>
      <div className="mt-3">
        <BadgeList badges={item.badges} />
      </div>
      {item.approval === 'pending' && <p className="mt-2 text-sm font-semibold text-accent-dark">아직 검토 중인 자료예요. 참고만 해 주세요.</p>}
      {item.sourceUrl && (
        <a href={item.sourceUrl} target="_blank" rel="noreferrer" className="mt-2 inline-block min-h-11 py-2 text-base font-semibold text-primary-dark underline">
          원문 보기 ↗
        </a>
      )}
    </article>
  )
}
