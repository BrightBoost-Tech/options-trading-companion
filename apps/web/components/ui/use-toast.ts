// Simplified useToast hook for missing shadcn component
import { useState, useEffect } from "react"

export function useToast() {
  const [toasts, setToasts] = useState<Array<{ id: string; title?: string; description?: string; variant?: "default" | "destructive" }>>([])

  const toast = ({ title, description, variant = "default" }: { title?: string; description?: string; variant?: "default" | "destructive" }) => {
    const id = Math.random().toString(36).substr(2, 9)
    const newToast = { id, title, description, variant }

    // Create a temporary visual element
    const el = document.createElement('div')
    el.id = `toast-${id}`
    el.style.position = 'fixed'
    el.style.bottom = '20px'
    el.style.right = '20px'
    el.style.padding = '16px'
    el.style.background = variant === 'destructive' ? '#fee2e2' : '#ffffff'
    el.style.color = variant === 'destructive' ? '#b91c1c' : '#1f2937'
    el.style.border = variant === 'destructive' ? '1px solid #fca5a5' : '1px solid #e5e7eb'
    el.style.borderRadius = '8px'
    el.style.boxShadow = '0 4px 6px -1px rgba(0, 0, 0, 0.1)'
    el.style.zIndex = '9999'
    el.style.minWidth = '300px'
    el.style.marginBottom = '10px'
    el.style.fontFamily = 'system-ui, -apple-system, sans-serif'

    const titleEl = document.createElement('div')
    titleEl.style.fontWeight = '600'
    titleEl.style.marginBottom = '4px'
    titleEl.textContent = title || ''

    const descEl = document.createElement('div')
    descEl.style.fontSize = '14px'
    descEl.textContent = description || ''

    el.appendChild(titleEl)
    el.appendChild(descEl)

    // Append to a container or body
    let container = document.getElementById('toast-container')
    if (!container) {
        container = document.createElement('div')
        container.id = 'toast-container'
        container.style.position = 'fixed'
        container.style.bottom = '0'
        container.style.right = '0'
        container.style.padding = '20px'
        container.style.zIndex = '9999'
        container.style.display = 'flex'
        container.style.flexDirection = 'column-reverse' // Newest at bottom/top depending on preference, usually bottom up
        document.body.appendChild(container)
    }

    container.appendChild(el)

    // Auto remove
    setTimeout(() => {
        el.style.opacity = '0'
        el.style.transition = 'opacity 0.5s ease-out'
        setTimeout(() => {
            if (el.parentNode) el.parentNode.removeChild(el)
        }, 500)
    }, 3000)
  }

  return {
    toast,
    dismiss: (toastId?: string) => {},
  }
}
