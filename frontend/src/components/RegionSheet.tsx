/**
 * 지역 선택 창. 1단계 시도 → 2단계 시군구. 시도는 데이터가 있는 서울·경기·전남만 보입니다.
 * - 선택 가능한 시도 및 시군구를 표시합니다.
 * - 시도를 바꾸면 시군구 선택은 초기화됩니다.
 * - "전국 공통만 보기"로 지역 없이도 질문할 수 있습니다.
 */
import { useEffect, useState } from 'react'
import { getRegions, isAbortError } from '../api'
import type { RegionOption, RegionSelection, RegionsData } from '../types/view'
import BigButton from './BigButton'
import BottomSheet from './BottomSheet'

type Props = {
  open: boolean
  onClose: () => void
  onSelect: (region: RegionSelection) => void
}

const gridButton = 'w-full rounded-button border border-line bg-surface px-3 py-2 text-left hover:border-primary-dark hover:bg-primary-soft'

type LoadState = { status: 'loading' } | { status: 'ready'; data: RegionsData } | { status: 'error'; message: string }

export default function RegionSheet({ open, onClose, onSelect }: Props) {
  const [sido, setSido] = useState<RegionOption | null>(null)
  const [reloadKey, setReloadKey] = useState(0)
  // 요청 결과를 "몇 번째 요청의 결과인지"와 함께 저장합니다.
  // 현재 요청 번호와 다르면 아직 로딩 중으로 봅니다. (effect 안에서 setState를 부르지 않기 위한 방식)
  const [result, setResult] = useState<{ key: number; state: LoadState } | null>(null)
  const load: LoadState = result?.key === reloadKey ? result.state : { status: 'loading' }

  useEffect(() => {
    if (!open) return
    const controller = new AbortController()
    const key = reloadKey
    getRegions({ signal: controller.signal })
      .then((data) => setResult({ key, state: { status: 'ready', data } }))
      .catch((err: unknown) => {
        if (isAbortError(err)) return
        setResult({ key, state: { status: 'error', message: '지역 목록을 불러오지 못했어요.' } })
      })
    return () => controller.abort()
  }, [open, reloadKey])

  function handleClose() {
    setSido(null) // 다음에 열 때 시도 선택부터 다시
    onClose()
  }

  function pick(region: RegionSelection) {
    onSelect(region)
    handleClose()
  }

  return (
    <BottomSheet open={open} title={sido ? `${sido.sidoName} 어디세요?` : '어디에 사세요?'} onClose={handleClose}>
      {load.status === 'loading' && <p className="py-6 text-center text-muted">불러오는 중…</p>}

      {load.status === 'error' && (
        <div className="py-4">
          <p className="font-semibold text-danger">{load.message}</p>
          <BigButton className="mt-3" onClick={() => setReloadKey((k) => k + 1)}>
            다시 시도
          </BigButton>
        </div>
      )}

      {load.status === 'ready' && !sido && (
        <>
          <BigButton variant="secondary" onClick={() => pick({ kind: 'nationwide' })}>
            🇰🇷 전국 공통 정책만 보기
          </BigButton>
          <p className="mb-2 mt-4 text-sm text-muted">지금은 {load.data.serviceScope.join(' · ')} 지역만 고를 수 있어요.</p>
          <ul className="grid grid-cols-2 gap-2">
            {load.data.regions.map((r) => (
              <li key={r.sidoName}>
                <button type="button" onClick={() => setSido(r)} className={`${gridButton} flex min-h-14 flex-col items-start justify-center`}>
                  <span className="text-base font-bold">{r.sidoName}</span>
                </button>
              </li>
            ))}
          </ul>
        </>
      )}

      {load.status === 'ready' && sido && (
        <>
          <button type="button" onClick={() => setSido(null)} className="mb-3 min-h-11 text-base font-semibold text-primary-dark">
            ← 다른 시·도 고르기
          </button>
          <BigButton variant="secondary" onClick={() => pick({ kind: 'region', sidoName: sido.sidoName, sigunguName: null })}>
            {sido.sidoName} 전체
          </BigButton>
          {sido.sigungu.length > 0 && (
            <ul className="mt-3 grid grid-cols-2 gap-2">
              {sido.sigungu.map((name) => (
                <li key={name}>
                  <button
                    type="button"
                    onClick={() => pick({ kind: 'region', sidoName: sido.sidoName, sigunguName: name })}
                    className={`${gridButton} min-h-12 text-center text-base font-semibold`}
                  >
                    {name}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </BottomSheet>
  )
}
