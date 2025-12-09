"use client"

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Loader2 } from "lucide-react"

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
  return (
    <AlertDialog open={open} onOpenChange={onClose}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Reset Paper Account?</AlertDialogTitle>
          <AlertDialogDescription>
            This will erase all paper trades, positions, and history and reset your paper account to the default starting balance of $100,000. This action cannot be undone.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={isResetting}>Cancel</AlertDialogCancel>
          <AlertDialogAction
            onClick={(e) => {
              e.preventDefault()
              onConfirm()
            }}
            disabled={isResetting}
            className="bg-red-600 hover:bg-red-700 focus:ring-red-600"
          >
            {isResetting ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Resetting...
              </>
            ) : (
              "Reset Account"
            )}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
