"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { AlertTriangle, CheckCircle2, Flag, Loader2, X } from "lucide-react";
import { Button } from "@/components/ui/button";

interface FinishDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void;
  totalQuestions: number;
  answeredCount: number;
  flaggedCount: number;
  isSubmitting?: boolean;
}

export function FinishDialog({
  open,
  onOpenChange,
  onConfirm,
  totalQuestions,
  answeredCount,
  flaggedCount,
  isSubmitting,
}: FinishDialogProps) {
  const unanswered = totalQuestions - answeredCount;

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/40 backdrop-blur-sm data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0" />
        <Dialog.Content className="fixed left-1/2 top-1/2 w-full max-w-md -translate-x-1/2 -translate-y-1/2 rounded-2xl border border-border/60 bg-card p-6 shadow-2xl focus:outline-none">
          <Dialog.Title className="text-xl font-semibold">
            Submit Assessment?
          </Dialog.Title>
          <Dialog.Description className="mt-2 text-sm text-muted-foreground">
            Review your progress before submitting for grading.
          </Dialog.Description>

          <div className="mt-5 space-y-3 rounded-xl bg-muted/50 p-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-sm">
                <CheckCircle2 className="h-4 w-4 text-success" />
                Answered
              </div>
              <span className="font-semibold tabular-nums text-success">
                {answeredCount}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <div className="h-4 w-4 rounded-full border-2 border-muted-foreground/30" />
                Unanswered
              </div>
              <span className="font-semibold tabular-nums text-muted-foreground">
                {unanswered}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-sm text-amber-600 dark:text-amber-400">
                <Flag className="h-4 w-4" />
                Flagged
              </div>
              <span className="font-semibold tabular-nums text-amber-600 dark:text-amber-400">
                {flaggedCount}
              </span>
            </div>
          </div>

          {unanswered > 0 && (
            <div className="mt-4 flex items-start gap-2 rounded-lg border border-amber-300/50 bg-amber-500/10 p-3 text-sm text-amber-700 dark:border-amber-700/50 dark:text-amber-300">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>
                {unanswered} unanswered question{unanswered > 1 ? "s" : ""} will
                be scored as 0.
              </span>
            </div>
          )}

          <div className="mt-6 flex justify-end gap-3">
            <Dialog.Close asChild>
              <Button variant="outline">Continue Assessment</Button>
            </Dialog.Close>
            <Button
              onClick={onConfirm}
              disabled={isSubmitting}
              className="bg-success hover:bg-success/90 text-white"
            >
              {isSubmitting ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Submitting...
                </>
              ) : (
                "Submit Assessment"
              )}
            </Button>
          </div>

          <Dialog.Close asChild>
            <button
              className="absolute right-4 top-4 rounded-lg p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
              aria-label="Close"
            >
              <X className="h-4 w-4" />
            </button>
          </Dialog.Close>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
