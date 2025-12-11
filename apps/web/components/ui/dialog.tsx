// apps/web/components/ui/dialog.tsx
"use client"

import * as React from "react"
import { cn } from "@/lib/utils"

type DialogProps = {
  open: boolean
  onOpenChange?: (open: boolean) => void
  children: React.ReactNode
}

export function Dialog({ open, children }: DialogProps) {
  if (!open) return null
  // we just render children; parent controls open state
  return <>{children}</>
}

type DialogContentProps = React.HTMLAttributes<HTMLDivElement> & {
  className?: string
}

export function DialogContent({ className, children, ...props }: DialogContentProps) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      {...props}
    >
      <div
        className={cn(
          "w-full max-w-md rounded-lg bg-white p-6 shadow-xl",
          className
        )}
      >
        {children}
      </div>
    </div>
  )
}

type DialogHeaderProps = React.HTMLAttributes<HTMLDivElement>
export function DialogHeader({ className, ...props }: DialogHeaderProps) {
  return <div className={cn("mb-3", className)} {...props} />
}

type DialogTitleProps = React.HTMLAttributes<HTMLHeadingElement>
export function DialogTitle({ className, ...props }: DialogTitleProps) {
  return <h2 className={cn("text-lg font-semibold", className)} {...props} />
}

type DialogDescriptionProps = React.HTMLAttributes<HTMLParagraphElement>
export function DialogDescription({ className, ...props }: DialogDescriptionProps) {
  return (
    <p
      className={cn("mt-1 text-sm text-gray-600", className)}
      {...props}
    />
  )
}

type DialogFooterProps = React.HTMLAttributes<HTMLDivElement>
export function DialogFooter({ className, ...props }: DialogFooterProps) {
  return (
    <div
      className={cn("mt-6 flex justify-end gap-3", className)}
      {...props}
    />
  )
}
