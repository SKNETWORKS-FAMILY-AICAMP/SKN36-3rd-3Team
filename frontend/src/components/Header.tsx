/**
 * 화면 맨 위 헤더 (피그마 시안: 초록 배경 + 흰 글자 + 흰색 둥근 버튼).
 * - 화면을 아래로 내려도 맨 위에 붙어 있습니다 (sticky).
 * - 홈이 아닌 화면에서는 [←] 뒤로 가기와 [🏠] 홈 버튼이 있어 어디서든 홈으로 돌아갈 수 있습니다.
 *   홈에서는 둘 다 없습니다 (누를 수 있는 것처럼 보이는 장식을 두지 않기 위해).
 * - 오른쪽: 글씨 가− / 가＋. 최소·최대에 닿으면 버튼이 비활성화되고 화면 읽기 프로그램에도 알립니다.
 * - 버튼은 피그마와 같은 46px(2.875rem)이라 손가락으로 누르기 쉽고, 글씨가 커지면 함께 커집니다.
 */
import { Link, useNavigate } from 'react-router-dom'
import { FONT_SCALE_STEPS, nextFontScale } from '../lib/fontScale'
import { useFontScale } from './fontScaleContext'

type Props = {
  title: string
  /** 홈이 아닌 화면: 뒤로 가기 + 홈 버튼 표시 */
  showBack?: boolean
  /** 뒤로 갈 곳이 없을 때(직접 진입) 대신 이동할 경로 */
  backFallback?: string
}

/** 초록 헤더 위의 흰색 둥근 버튼 */
const chip =
  'flex size-[2.875rem] shrink-0 items-center justify-center rounded-button bg-surface font-bold text-ink hover:bg-primary-soft disabled:opacity-50'

export default function Header({ title, showBack = false, backFallback = '/' }: Props) {
  const navigate = useNavigate()
  const { scale, setScale } = useFontScale()
  const isMin = scale === FONT_SCALE_STEPS[0]
  const isMax = scale === FONT_SCALE_STEPS[FONT_SCALE_STEPS.length - 1]

  function goBack() {
    if (window.history.length > 1) navigate(-1)
    else navigate(backFallback)
  }

  return (
    // flex-wrap: 좁은 화면·큰 글씨에서 자리가 모자라면 글씨 버튼 묶음이 다음 줄로 내려갑니다 (버튼끼리 겹치지 않음)
    <header className="sticky top-0 z-10 flex flex-wrap items-center gap-x-2 gap-y-1 bg-primary px-3 py-2 text-on-primary shadow-md">
      <div className="flex min-w-0 flex-1 basis-40 items-center gap-2">
        {showBack && (
          <>
            <button type="button" onClick={goBack} aria-label="뒤로 가기" className={`${chip} text-2xl`}>
              ←
            </button>
            <Link to="/" aria-label="홈으로" title="홈으로" className={`${chip} text-2xl`}>
              🏠
            </Link>
          </>
        )}
        <h1 className="truncate py-2 text-xl font-bold leading-tight">{title}</h1>
      </div>

      <div className="ml-auto flex shrink-0 items-center gap-1" role="group" aria-label="글씨 크기">
        <button type="button" onClick={() => setScale(nextFontScale(scale, -1))} disabled={isMin} aria-label="글씨 작게" className={`${chip} text-base`}>
          가−
        </button>
        <button type="button" onClick={() => setScale(nextFontScale(scale, 1))} disabled={isMax} aria-label="글씨 크게" className={`${chip} text-lg`}>
          가＋
        </button>
      </div>
    </header>
  )
}
