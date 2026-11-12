/**
 * 아래에서 올라오는 창 (피그마 14:141 "Bottom Sheet").
 * - 브라우저 기본 <dialog>를 써서 포커스 가두기, ESC 닫기, 뒷배경 클릭 닫기를 쉽게 얻습니다.
 * - 열릴 때 제목에 포커스를 주고, 닫히면 열기 전에 누르던 버튼으로 포커스를 돌려 줍니다.
 */
import { useEffect, useRef, type ReactNode } from 'react'

type Props = {
  open: boolean
  title: string
  onClose: () => void
  children: ReactNode
}

export default function BottomSheet({ open, title, onClose, children }: Props) {
  const dialogRef = useRef<HTMLDialogElement>(null)
  const titleRef = useRef<HTMLHeadingElement>(null)
  const openerRef = useRef<Element | null>(null)

  useEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return
    if (open && !dialog.open) {
      openerRef.current = document.activeElement
      dialog.showModal()
      titleRef.current?.focus()
    } else if (!open && dialog.open) {
      dialog.close()
    }
  }, [open])

  function handleClose() {
    onClose()
    const opener = openerRef.current
    if (opener instanceof HTMLElement) opener.focus()
  }

  return (
    <dialog
      ref={dialogRef}
      onClose={handleClose}
      onClick={(e) => {
        // 창 바깥(뒷배경)을 누르면 닫기
        if (e.target === e.currentTarget) dialogRef.current?.close()
      }}
      className="fixed inset-x-0 bottom-0 top-auto m-0 w-full max-w-[30rem] translate-x-0 rounded-t-3xl bg-surface p-0 open:flex open:flex-col [margin-inline:auto]"
      style={{ maxHeight: '85svh' }}
    >
      <div className="mx-auto mt-3 h-1.5 w-12 rounded-full bg-line" aria-hidden />
      <div className="flex items-center justify-between px-5 pb-2 pt-4">
        <h2 ref={titleRef} tabIndex={-1} className="text-xl font-bold outline-none">
          {title}
        </h2>
        <button
          type="button"
          onClick={() => dialogRef.current?.close()}
          aria-label="닫기"
          className="flex size-[2.875rem] items-center justify-center rounded-button text-2xl hover:bg-primary-soft"
        >
          ✕
        </button>
      </div>
      <div className="overflow-y-auto px-5 pb-6">{children}</div>
    </dialog>
  )
}
