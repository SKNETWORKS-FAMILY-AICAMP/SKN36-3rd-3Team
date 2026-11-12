/**
 * 전화 걸기 버튼. 휴대폰에서 누르면 바로 전화 앱이 열립니다 (tel: 링크).
 * - 피그마 시안: 주황(#E67E22) 채움 + 흰 글자. 초록 행동 버튼과 색·아이콘·문구로 구분됩니다.
 * - 카드 전체가 링크인 곳에서는 카드 "밖"에 둬야 링크가 겹치지 않습니다.
 */
import type { Contact } from '../types/view'

export default function PhoneButton({ contact, compact = false }: { contact: Contact; compact?: boolean }) {
  const telHref = `tel:${contact.tel.replace(/[^\d+]/g, '')}`
  return (
    <a
      href={telHref}
      className={`flex items-center justify-center gap-2 rounded-button bg-accent font-bold text-on-accent hover:bg-accent-dark ${
        compact ? 'min-h-12 px-3 py-2 text-lg' : 'min-h-14 w-full px-4 py-3 text-lg'
      }`}
    >
      <span aria-hidden>📞</span>
      <span>
        {contact.label} {contact.tel} 전화
      </span>
    </a>
  )
}
