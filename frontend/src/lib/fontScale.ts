/**
 * 글씨 크기 조절 (헤더의 가− / 가＋ 버튼).
 *
 * - <html>의 font-size를 %로 바꾸면, rem 단위로 적은 모든 글자·여백·버튼이 함께 커집니다.
 *   (index.css 참고) 그래서 100%를 기준으로 몇 단계만 허용합니다.
 * - 고정 px가 아니라 %를 쓰는 이유: 어르신이 휴대폰 설정에서 이미 글씨를 키워 뒀다면
 *   그 설정 위에 더 키워져야 하기 때문입니다.
 * - localStorage는 사생활 보호 모드 등에서 실패할 수 있어 전부 try/catch로 감쌉니다.
 */

export const FONT_SCALE_STEPS = [100, 112.5, 125, 137.5] as const
export type FontScale = (typeof FONT_SCALE_STEPS)[number]

export const DEFAULT_FONT_SCALE: FontScale = 100
const STORAGE_KEY = 'welfare-ui.fontScale'

function isFontScale(value: unknown): value is FontScale {
  return typeof value === 'number' && (FONT_SCALE_STEPS as readonly number[]).includes(value)
}

/** 저장된 값을 읽습니다. 없거나 깨졌으면 기본값 */
export function loadFontScale(): FontScale {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    const parsed = raw === null ? null : Number(raw)
    return isFontScale(parsed) ? parsed : DEFAULT_FONT_SCALE
  } catch {
    return DEFAULT_FONT_SCALE
  }
}

export function saveFontScale(scale: FontScale): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, String(scale))
  } catch {
    // 저장 실패는 무시합니다. 화면 동작에는 영향 없음.
  }
}

/** 실제로 <html>에 적용 */
export function applyFontScale(scale: FontScale): void {
  document.documentElement.style.fontSize = `${scale}%`
}

export function nextFontScale(current: FontScale, direction: 1 | -1): FontScale {
  const index = FONT_SCALE_STEPS.indexOf(current)
  const nextIndex = Math.min(FONT_SCALE_STEPS.length - 1, Math.max(0, index + direction))
  return FONT_SCALE_STEPS[nextIndex]
}
