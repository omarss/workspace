"use client";

import { Check, Loader2, AlertCircle, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAssessmentStore, type SaveStatus } from "@/lib/stores/assessment-store";
import { cn } from "@/lib/utils";

interface SaveIndicatorProps {
  onRetry?: () => void;
  className?: string;
}

const STATUS_CONFIG: Record<
  SaveStatus,
  { icon: React.ComponentType<{ className?: string }>; label: string; color: string }
> = {
  idle: { icon: Check, label: "Ready", color: "text-muted-foreground" },
  saving: { icon: Loader2, label: "Saving...", color: "text-primary" },
  saved: { icon: Check, label: "Saved", color: "text-success" },
  error: { icon: AlertCircle, label: "Failed", color: "text-destructive" },
};

export function SaveIndicator({ onRetry, className }: SaveIndicatorProps) {
  const saveStatus = useAssessmentStore((s) => s.saveStatus);
  const config = STATUS_CONFIG[saveStatus];
  const Icon = config.icon;

  return (
    <div
      className={cn("flex items-center gap-1.5 text-xs font-medium", config.color, className)}
      role="status"
      aria-live="polite"
      aria-label={`Save status: ${config.label}`}
    >
      <Icon
        className={cn("h-3.5 w-3.5", saveStatus === "saving" && "animate-spin")}
      />
      <span>{config.label}</span>
      {saveStatus === "error" && onRetry && (
        <Button
          variant="ghost"
          size="sm"
          className="h-5 px-1.5 text-xs"
          onClick={onRetry}
        >
          <RefreshCw className="h-3 w-3" />
        </Button>
      )}
    </div>
  );
}
