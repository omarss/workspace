"use client";

import * as Progress from "@radix-ui/react-progress";
import { cn } from "@/lib/utils";

interface ProgressBarProps {
  current: number;
  total: number;
  className?: string;
}

export function ProgressBar({ current, total, className }: ProgressBarProps) {
  const percentage = total > 0 ? Math.round((current / total) * 100) : 0;

  return (
    <div className={cn("flex items-center gap-3", className)}>
      <span className="text-sm font-medium tabular-nums text-muted-foreground">
        {current}/{total}
      </span>
      <Progress.Root
        className="relative h-2.5 flex-1 overflow-hidden rounded-full bg-muted"
        value={percentage}
        role="progressbar"
        aria-label={`Assessment progress: ${current} of ${total} questions answered`}
        aria-valuenow={percentage}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <Progress.Indicator
          className="h-full rounded-full bg-gradient-to-r from-primary to-primary/80 transition-transform duration-500 ease-out"
          style={{ transform: `translateX(-${100 - percentage}%)` }}
        />
      </Progress.Root>
      <span className="min-w-[2.5rem] text-right text-xs font-semibold text-primary tabular-nums">
        {percentage}%
      </span>
    </div>
  );
}
