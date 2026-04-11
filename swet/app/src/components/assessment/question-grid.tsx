"use client";

import { cn } from "@/lib/utils";
import { useAssessmentStore } from "@/lib/stores/assessment-store";

interface QuestionGridProps {
  total: number;
  answeredIds: Set<string>;
  questionIds: string[];
  onNavigate: (index: number) => void;
  className?: string;
}

/**
 * 10x10 grid sidebar showing question navigation status.
 * Color-coded: unanswered (neutral), answered (green), flagged (amber), current (ring).
 */
export function QuestionGrid({
  total,
  answeredIds,
  questionIds,
  onNavigate,
  className,
}: QuestionGridProps) {
  const currentIndex = useAssessmentStore((s) => s.currentIndex);
  const flaggedQuestions = useAssessmentStore((s) => s.flaggedQuestions);

  return (
    <div
      className={cn("grid grid-cols-10 gap-1.5", className)}
      role="navigation"
      aria-label="Question navigation grid"
    >
      {Array.from({ length: total }, (_, i) => {
        const isCurrent = i === currentIndex;
        const isAnswered = questionIds[i] ? answeredIds.has(questionIds[i]) : false;
        const isFlagged = flaggedQuestions.has(i);

        return (
          <button
            key={i}
            onClick={() => onNavigate(i)}
            className={cn(
              "flex h-7 w-7 items-center justify-center rounded-md text-[11px] font-semibold transition-all",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              isCurrent && "ring-2 ring-primary ring-offset-1 ring-offset-background",
              isFlagged && "bg-amber-500/90 text-white shadow-sm",
              !isFlagged && isAnswered && "bg-success/90 text-white shadow-sm",
              !isFlagged && !isAnswered && "bg-muted text-muted-foreground hover:bg-muted/80"
            )}
            aria-label={`Question ${i + 1}${isAnswered ? ", answered" : ""}${isFlagged ? ", flagged" : ""}${isCurrent ? ", current" : ""}`}
            aria-current={isCurrent ? "step" : undefined}
          >
            {i + 1}
          </button>
        );
      })}

      {/* Legend */}
      <div className="col-span-10 mt-3 flex items-center gap-4 border-t border-border/50 pt-3 text-[10px] text-muted-foreground">
        <div className="flex items-center gap-1">
          <div className="h-2.5 w-2.5 rounded-sm bg-muted" />
          <span>Open</span>
        </div>
        <div className="flex items-center gap-1">
          <div className="h-2.5 w-2.5 rounded-sm bg-success/90" />
          <span>Done</span>
        </div>
        <div className="flex items-center gap-1">
          <div className="h-2.5 w-2.5 rounded-sm bg-amber-500/90" />
          <span>Flagged</span>
        </div>
      </div>
    </div>
  );
}
