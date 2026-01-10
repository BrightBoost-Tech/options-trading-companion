"use client"

import * as React from "react"
import { Check } from "lucide-react"
import { cn } from "@/lib/utils"

export interface CheckboxProps extends React.InputHTMLAttributes<HTMLInputElement> {}

const Checkbox = React.forwardRef<HTMLInputElement, CheckboxProps>(
  ({ className, ...props }, ref) => (
    <div className="relative inline-flex items-center justify-center w-4 h-4 align-middle">
        <input
            type="checkbox"
            className={cn(
                "peer h-4 w-4 shrink-0 rounded-sm border border-input ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 appearance-none checked:bg-primary checked:border-primary checked:text-primary-foreground cursor-pointer",
                className
            )}
            ref={ref}
            {...props}
        />
        <Check className="absolute h-3 w-3 text-primary-foreground opacity-0 peer-checked:opacity-100 pointer-events-none" strokeWidth={3} />
    </div>
  )
)
Checkbox.displayName = "Checkbox"

export { Checkbox }
