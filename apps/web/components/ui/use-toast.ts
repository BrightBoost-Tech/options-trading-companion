// Simplified useToast hook for missing shadcn component
import { useState } from "react"

export function useToast() {
  const [toasts, setToasts] = useState<Array<{ id: string; title?: string; description?: string; variant?: "default" | "destructive" }>>([])

  const toast = ({ title, description, variant = "default" }: { title?: string; description?: string; variant?: "default" | "destructive" }) => {
    const id = Math.random().toString(36).substr(2, 9)

    // Create visual element
    const el = document.createElement('div')
    el.id = `toast-${id}`

    // Tailwind classes
    // Container handles positioning (flex-col-reverse)
    // We add pointer-events-auto to the toast so it can be clicked
    const baseClasses = "relative p-4 rounded-lg shadow-lg min-w-[300px] mb-3 font-sans transition-all duration-300 ease-out border translate-y-2 opacity-0 data-[state=open]:translate-y-0 data-[state=open]:opacity-100 pointer-events-auto cursor-pointer flex flex-col gap-1"

    const variantClasses = variant === 'destructive'
        ? "bg-destructive text-destructive-foreground border-destructive"
        : "bg-background text-foreground border-border"

    el.className = `${baseClasses} ${variantClasses}`

    // A11y
    el.setAttribute("role", variant === "destructive" ? "alert" : "status")

    // Title
    if (title) {
        const titleEl = document.createElement('div')
        titleEl.className = "font-semibold text-sm"
        titleEl.textContent = title
        el.appendChild(titleEl)
    }

    // Description
    if (description) {
        const descEl = document.createElement('div')
        descEl.className = "text-sm opacity-90"
        descEl.textContent = description
        el.appendChild(descEl)
    }

    // Append to a container or body
    let container = document.getElementById('toast-container')
    if (!container) {
        container = document.createElement('div')
        container.id = 'toast-container'
        // Container is fixed, but lets clicks pass through (pointer-events-none)
        container.className = "fixed bottom-0 right-0 p-5 z-[9999] flex flex-col-reverse pointer-events-none max-h-screen overflow-hidden"
        container.setAttribute("aria-live", "polite")
        document.body.appendChild(container)
    }

    container.appendChild(el)

    // Animation entry
    requestAnimationFrame(() => {
        el.setAttribute("data-state", "open")
    })

    const remove = () => {
        el.removeAttribute("data-state") // triggers exit transition if defined in CSS, but here we rely on classes
        el.classList.remove("opacity-100", "translate-y-0")
        el.classList.add("opacity-0", "translate-y-2")

        setTimeout(() => {
            if (el.parentNode) el.parentNode.removeChild(el)
        }, 300)
    }

    // Auto remove
    setTimeout(remove, 4000)

    // Click to dismiss
    el.onclick = remove
  }

  return {
    toast,
    dismiss: (toastId?: string) => {},
  }
}
