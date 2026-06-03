"use client"

import React from "react"
import { Button } from "@/components/ui/button"

interface ResetPaperAccountModalProps {
  open: boolean
  onClose: () => void
  onConfirm: () => Promise<void>
  isResetting: boolean
}

export function ResetPaperAccountModal({
  open,
  onClose,
  onConfirm,
  isResetting,
}: ResetPaperAccountModalProps) {
  if (!open) return null

  const handleBackdropClick = (e: React.MouseEvent<HTMLDivElement>) => {
    // close only if they click the dimmed backdrop, not inside the card
    if (e.target === e.currentTarget && !isResetting) {
      onClose()
    }
  }

  const handleConfirm = async (e: React.MouseEvent<HTMLButtonElement>) => {
    e.preventDefault()
    if (isResetting) return
    await onConfirm()
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={handleBackdropClick}
    >
      <div className="w-full max-w-md rounded-lg bg-white p-6 shadow-xl">
        <h2 className="text-lg font-semibold text-gray-900">
          Reset Paper Account?
        </h2>
        <p className="mt-2 text-sm text-gray-600">
          This will erase all paper trades, positions, and history and reset
          your paper account to the default starting balance of $100,000.
          This action cannot be undone.
        </p>

        <div className="mt-6 flex justify-end gap-3">
          <Button
            type="button"
            variant="outline"
            onClick={onClose}
            disabled={isResetting}
          >
            Cancel
          </Button>
          <Button
            type="button"
            variant="destructive"
            onClick={handleConfirm}
            loading={isResetting}
          >
            {isResetting ? "Resetting..." : "Reset Account"}
          </Button>
        </div>
      </div>
    </div>
  )
}
