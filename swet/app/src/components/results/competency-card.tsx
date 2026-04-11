"use client";

import type { CompetencyScore } from "@/lib/types";
import { cn } from "@/lib/utils";

const LEVEL_CONFIG = [
  { label: "Novice", color: "bg-red-500", badge: "text-red-700 bg-red-500/10 dark:text-red-300" },
  { label: "Beginner", color: "bg-orange-500", badge: "text-orange-700 bg-orange-500/10 dark:text-orange-300" },
  { label: "Intermediate", color: "bg-yellow-500", badge: "text-yellow-700 bg-yellow-500/10 dark:text-yellow-300" },
  { label: "Advanced", color: "bg-blue-500", badge: "text-blue-700 bg-blue-500/10 dark:text-blue-300" },
  { label: "Expert", color: "bg-emerald-500", badge: "text-emerald-700 bg-emerald-500/10 dark:text-emerald-300" },
];

interface CompetencyCardProps {
  score: CompetencyScore;
}

export function CompetencyCard({ score }: CompetencyCardProps) {
  const levelIndex = Math.max(0, Math.min(4, score.proficiency_level - 1));
  const config = LEVEL_CONFIG[levelIndex];

  return (
    <div className="rounded-xl border border-border/60 bg-card p-4 transition-shadow hover:shadow-md">
      <div className="mb-3 flex items-start justify-between gap-2">
        <h3 className="text-sm font-semibold leading-tight">
          {score.competency_name ?? `Competency ${score.competency_id}`}
        </h3>
        <span
          className={cn(
            "shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
            config.badge
          )}
        >
          {config.label}
        </span>
      </div>

      {/* Score bar */}
      <div className="mb-3 h-2 w-full overflow-hidden rounded-full bg-muted">
        <div
          className={cn("h-full rounded-full transition-all duration-500", config.color)}
          style={{ width: `${Math.min(100, score.score)}%` }}
        />
      </div>

      <div className="flex items-center justify-between text-xs">
        <span className="font-semibold tabular-nums">
          {score.score.toFixed(1)}%
        </span>
        <span className="text-muted-foreground">
          {score.questions_correct}/{score.questions_total} correct
        </span>
      </div>

      {score.ai_graded_avg !== null && (
        <p className="mt-2 text-xs text-muted-foreground">
          AI evaluation avg: {(score.ai_graded_avg * 100).toFixed(0)}%
        </p>
      )}
    </div>
  );
}
