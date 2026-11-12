/**
 * 글씨 크기 설정을 앱 전체에 나눠 주는 Context.
 * (AppShell이 값을 넣어 주고, Header가 useFontScale()로 읽습니다)
 * 컴포넌트 파일과 분리한 이유: 한 파일에 컴포넌트와 일반 함수를 같이 export하면
 * 개발 중 "빠른 새로고침"이 제대로 동작하지 않기 때문입니다.
 */
import { createContext, useContext } from 'react'
import type { FontScale } from '../lib/fontScale'

export type FontScaleContextValue = { scale: FontScale; setScale: (next: FontScale) => void }

export const FontScaleContext = createContext<FontScaleContextValue | null>(null)

export function useFontScale(): FontScaleContextValue {
  const value = useContext(FontScaleContext)
  if (!value) throw new Error('useFontScale은 AppShell 안에서만 쓸 수 있어요.')
  return value
}
