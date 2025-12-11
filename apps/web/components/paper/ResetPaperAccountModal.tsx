"use client"

import { Loader2 } from "lucide-react"
import React from "react"

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
          <button
            type="button"
            onClick={onClose}
            disabled={isResetting}
            className="inline-flex items-center rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleConfirm}
            disabled={isResetting}
            className="inline-flex items-center rounded-md bg-red-600 px-3 py-1.5 text-sm font-medium text-white shadow-sm hover:bg-red-700 disabled:opacity-50"
          >
            {isResetting && (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            )}
            {isResetting ? "Resetting..." : "Reset Account"}
          </button>
        </div>
      </div>
    </div>
  )
}
