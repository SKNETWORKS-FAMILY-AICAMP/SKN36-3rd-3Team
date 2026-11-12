/**
 * 앱 전체를 감싸는 틀.
 * - 글씨 크기 설정을 한 번만 읽어서 <html>에 적용하고, 하위 컴포넌트에 Context로 나눠 줍니다.
 * - 화면 폭은 피그마(390px)를 기준으로 최대 480px까지만 늘어나게 가운데 정렬합니다.
 * - 배경은 피그마 크림색(bg), 카드만 흰색입니다.
 */
import { useEffect, useState, type ReactNode } from 'react'
import { Outlet } from 'react-router-dom'
import { applyFontScale, loadFontScale, saveFontScale, type FontScale } from '../lib/fontScale'
import { FontScaleContext } from './fontScaleContext'

export default function AppShell({ children }: { children?: ReactNode }) {
  const [scale, setScaleState] = useState<FontScale>(() => loadFontScale())

  useEffect(() => {
    applyFontScale(scale)
  }, [scale])

  function setScale(next: FontScale) {
    setScaleState(next)
    saveFontScale(next)
  }

  return (
    <FontScaleContext.Provider value={{ scale, setScale }}>
      {/* PC처럼 넓은 화면(640px 이상)에서는 앱 영역 좌우에 구분선을 그어 바깥 배경과 구분합니다. 휴대폰에서는 선 없음 */}
      <div className="mx-auto flex min-h-svh w-full max-w-[30rem] flex-col bg-bg sm:border-x-[3px] sm:border-ink">
        <div className="flex-1">{children ?? <Outlet />}</div>
      </div>
    </FontScaleContext.Provider>
  )
}
