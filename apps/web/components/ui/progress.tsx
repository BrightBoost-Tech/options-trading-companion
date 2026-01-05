"use client"

import * as React from "react"
import { cn } from "@/lib/utils"

type ProgressProps = React.HTMLAttributes<HTMLDivElement> & {
  value?: number // 0..100
}

const clamp = (n: number, min: number, max: number) => Math.min(max, Math.max(min, n))

const Progress = React.forwardRef<HTMLDivElement, ProgressProps>(
  ({ className, value = 0, ...props }, ref) => {
    const v = clamp(Number.isFinite(value) ? value : 0, 0, 100)

    return (
      <div
        ref={ref}
        className={cn(
          "relative h-4 w-full overflow-hidden rounded-full bg-secondary",
          className
        )}
        {...props}
      >
        <div
          className="h-full bg-primary transition-all"
          style={{ width: `${v}%` }}
        />
      </div>
    )
  }
)

Progress.displayName = "Progress"

export { Progress }
