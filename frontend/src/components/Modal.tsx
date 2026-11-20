import { useEffect, useRef, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { Icon } from './Icon'

/**
 * Centered dialog. Closes on Esc, on the close button, or on a click outside the panel.
 * Locks page scroll while open and returns focus to the element that opened it.
 */
export function Modal({
  title,
  subtitle,
  leading,
  actions,
  footer,
  onClose,
  onKeyDown,
  children,
  labelledBy = 'modal-title',
  size,
}: {
  title: ReactNode
  subtitle?: ReactNode
  leading?: ReactNode
  actions?: ReactNode
  footer?: ReactNode
  onClose: () => void
  onKeyDown?: (e: KeyboardEvent) => void
  children: ReactNode
  labelledBy?: string
  size?: 'sm'
}) {
  const panelRef = useRef<HTMLDivElement>(null)
  const onCloseRef = useRef(onClose)
  const onKeyRef = useRef(onKeyDown)
  useEffect(() => {
    onCloseRef.current = onClose
    onKeyRef.current = onKeyDown
  })

  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null
    const { overflow } = document.body.style
    document.body.style.overflow = 'hidden'
    panelRef.current?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onCloseRef.current()
      else onKeyRef.current?.(e)
    }
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = overflow
      opener?.focus?.()
    }
  }, [])

  return createPortal(
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal${size ? ` ${size}` : ''}`} role="dialog" aria-modal="true" aria-labelledby={labelledBy} tabIndex={-1} ref={panelRef}>
        <header className="modal-head">
          {leading}
          <div className="grow">
            <h2 id={labelledBy} className="truncate">
              {title}
            </h2>
            {subtitle && <p className="truncate">{subtitle}</p>}
          </div>
          {actions && <div className="modal-actions">{actions}</div>}
          <button className="btn btn-ghost btn-icon modal-close" onClick={onClose} aria-label="Close" title="Close (Esc)">
            <Icon name="x" />
          </button>
        </header>
        <div className="modal-body">{children}</div>
        {footer && <footer className="modal-foot">{footer}</footer>}
      </div>
    </div>,
    document.body,
  )
}
