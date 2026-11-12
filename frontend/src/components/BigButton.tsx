/**
 * 큰 버튼 (피그마 "🔎 질문하기" 등 행동 버튼).
 * - 최소 높이 3.5rem(56px)으로 손가락 터치가 쉽고, 글씨가 커져도 함께 커집니다.
 * 피그마 시안의 버튼 종류:
 * - primary:   초록 채움 + 흰 글자 ("🔎 질문하기", "이대로 질문", "길 찾기")
 * - secondary: 흰 배경 + 초록 테두리 + 초록 글자 ("다시 말하기")
 * - accent:    주황 채움 + 흰 글자 ("신청처 전화" 같은 전화 계열, PhoneButton과 같은 색)
 * - ghost:     흰 카드형 (자주 찾는 복지, 복지로 링크)
 * - to가 있으면 링크(<a>), 없으면 <button>으로 렌더링합니다.
 */
import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { Link } from 'react-router-dom'

type Variant = 'primary' | 'secondary' | 'accent' | 'ghost'

const variantClass: Record<Variant, string> = {
  primary: 'bg-primary text-on-primary hover:bg-primary-dark disabled:bg-line-soft disabled:text-muted',
  secondary: 'bg-surface text-primary-dark border-2 border-primary hover:bg-primary-soft',
  accent: 'bg-accent text-on-accent hover:bg-accent-dark',
  ghost: 'bg-surface text-ink border border-line hover:border-primary hover:bg-primary-soft',
}

const base =
  'flex min-h-14 w-full items-center justify-center gap-2 rounded-button px-4 py-3 text-center text-lg font-bold leading-snug disabled:cursor-not-allowed'

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; children: ReactNode; to?: undefined }
type LinkProps = { to: string; variant?: Variant; children: ReactNode; className?: string }

export default function BigButton(props: ButtonProps | LinkProps) {
  const variant = props.variant ?? 'primary'
  if ('to' in props && props.to !== undefined) {
    const { to, children, className = '' } = props
    const external = /^https?:/.test(to)
    if (external) {
      return (
        <a href={to} target="_blank" rel="noreferrer" className={`${base} ${variantClass[variant]} ${className}`}>
          {children}
        </a>
      )
    }
    return (
      <Link to={to} className={`${base} ${variantClass[variant]} ${className}`}>
        {children}
      </Link>
    )
  }
  const { children, className = '', variant: _v, ...rest } = props as ButtonProps
  return (
    <button type="button" {...rest} className={`${base} ${variantClass[variant]} ${className}`}>
      {children}
    </button>
  )
}
