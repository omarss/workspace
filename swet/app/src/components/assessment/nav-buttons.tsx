"use client";

import { ChevronLeft, ChevronRight, Flag, Send } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAssessmentStore } from "@/lib/stores/assessment-store";
import { cn } from "@/lib/utils";

interface NavButtonsProps {
  total: number;
  onNavigate: (index: number) => void;
  onFinish: () => void;
  className?: string;
}

export function NavButtons({ total, onNavigate, onFinish, className }: NavButtonsProps) {
  const currentIndex = useAssessmentStore((s) => s.currentIndex);
  const flaggedQuestions = useAssessmentStore((s) => s.flaggedQuestions);
  const toggleFlag = useAssessmentStore((s) => s.toggleFlag);

  const isFirst = currentIndex === 0;
  const isLast = currentIndex === total - 1;
  const isFlagged = flaggedQuestions.has(currentIndex);

  return (
    <div className={cn("flex items-center justify-between", className)}>
      <Button
        variant="outline"
        onClick={() => onNavigate(currentIndex - 1)}
        disabled={isFirst}
        aria-label="Previous question"
      >
        <ChevronLeft className="h-4 w-4" />
        Previous
      </Button>

      <Button
        variant={isFlagged ? "secondary" : "ghost"}
        onClick={() => toggleFlag(currentIndex)}
        aria-label={isFlagged ? "Remove flag" : "Flag for review"}
        aria-pressed={isFlagged}
        className={cn(isFlagged && "text-amber-600 dark:text-amber-400")}
      >
        <Flag className="h-4 w-4" />
        {isFlagged ? "Flagged" : "Flag"}
      </Button>

      {isLast ? (
        <Button onClick={onFinish} className="bg-success hover:bg-success/90 text-white shadow-md shadow-success/20">
          <Send className="h-4 w-4" />
          Finish
        </Button>
      ) : (
        <Button onClick={() => onNavigate(currentIndex + 1)} aria-label="Next question">
          Next
          <ChevronRight className="h-4 w-4" />
        </Button>
      )}
    </div>
  );
}
