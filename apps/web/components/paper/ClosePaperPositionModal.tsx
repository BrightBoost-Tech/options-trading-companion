"use client"

import { useState } from "react"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Loader2 } from "lucide-react"

interface ClosePaperPositionModalProps {
  position: any | null
  open: boolean
  onClose: () => void
  onConfirm: (positionId: string) => Promise<void>
}

export function ClosePaperPositionModal({
  position,
  open,
  onClose,
  onConfirm,
}: ClosePaperPositionModalProps) {
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (!position) return null

  const handleConfirm = async () => {
    setIsLoading(true)
    setError(null)
    try {
      await onConfirm(position.id)
      onClose()
    } catch (err: any) {
      setError(err.message || "Failed to close position")
    } finally {
      setIsLoading(false)
    }
  }

  // Estimate P/L
  const entry = position.avg_entry_price || 0
  const mark = position.current_mark || entry // fallback
  const qty = position.quantity || 0
  const multiplier = 100 // assuming options
  const estimatedPl = (mark - entry) * qty * multiplier

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="sm:max-w-[425px] bg-background border-border">
        <DialogHeader>
          <DialogTitle>Close Paper Position</DialogTitle>
          <DialogDescription>
            Are you sure you want to close this position? This action cannot be undone.
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-4 py-4">
          <div className="flex items-center justify-between p-3 border rounded-md bg-muted/50">
            <div className="font-semibold">{position.symbol}</div>
            <div className="text-sm text-muted-foreground">{position.strategy_key}</div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1">
              <span className="text-xs text-muted-foreground">Quantity</span>
              <div className="font-mono">{qty}</div>
            </div>
            <div className="space-y-1">
              <span className="text-xs text-muted-foreground">Entry Price</span>
              <div className="font-mono">${entry.toFixed(2)}</div>
            </div>
            <div className="space-y-1">
              <span className="text-xs text-muted-foreground">Current Mark</span>
              <div className="font-mono">${mark.toFixed(2)}</div>
            </div>
            <div className="space-y-1">
              <span className="text-xs text-muted-foreground">Est. P/L</span>
              <div className={`font-mono font-bold ${estimatedPl >= 0 ? "text-green-500" : "text-red-500"}`}>
                {estimatedPl >= 0 ? "+" : ""}{estimatedPl.toFixed(2)}
              </div>
            </div>
          </div>

          {error && (
            <div className="text-sm text-red-500 bg-red-500/10 p-2 rounded border border-red-500/20">
              {error}
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={isLoading}>
            Cancel
          </Button>
          <Button onClick={handleConfirm} disabled={isLoading} variant={estimatedPl < 0 ? "destructive" : "default"}>
            {isLoading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            Confirm Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
