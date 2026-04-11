"use client";

import { Award, Clock, Calendar, TrendingUp } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import type { AssessmentResult } from "@/lib/types";

const PROFICIENCY_STYLES: Record<string, { bg: string; text: string; border: string }> = {
  novice: { bg: "bg-red-500/10", text: "text-red-700 dark:text-red-300", border: "border-red-500/20" },
  beginner: { bg: "bg-orange-500/10", text: "text-orange-700 dark:text-orange-300", border: "border-orange-500/20" },
  intermediate: { bg: "bg-yellow-500/10", text: "text-yellow-700 dark:text-yellow-300", border: "border-yellow-500/20" },
  advanced: { bg: "bg-blue-500/10", text: "text-blue-700 dark:text-blue-300", border: "border-blue-500/20" },
  expert: { bg: "bg-emerald-500/10", text: "text-emerald-700 dark:text-emerald-300", border: "border-emerald-500/20" },
};

function formatTime(seconds: number): string {
  const hrs = Math.floor(seconds / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  const secs = seconds % 60;
  if (hrs > 0) return `${hrs}h ${mins}m ${secs}s`;
  if (mins > 0) return `${mins}m ${secs}s`;
  return `${secs}s`;
}

interface ResultSummaryProps {
  result: AssessmentResult;
}

export function ResultSummary({ result }: ResultSummaryProps) {
  const style =
    PROFICIENCY_STYLES[result.proficiency_label] ?? PROFICIENCY_STYLES.novice;

  return (
    <Card className="overflow-hidden">
      {/* Score hero */}
      <div className="bg-gradient-to-br from-primary/5 via-primary/10 to-accent p-8 text-center">
        <p className="mb-2 text-sm font-medium uppercase tracking-wider text-muted-foreground">
          Overall Score
        </p>
        <p className="text-6xl font-bold tabular-nums text-foreground">
          {result.overall_score.toFixed(1)}
          <span className="text-2xl font-normal text-muted-foreground">
            %
          </span>
        </p>
        <div className="mt-4 inline-flex items-center gap-2">
          <span
            className={`rounded-full border px-4 py-1.5 text-sm font-semibold capitalize ${style.bg} ${style.text} ${style.border}`}
          >
            <Award className="mr-1 inline h-3.5 w-3.5" />
            {result.proficiency_label}
          </span>
        </div>
      </div>

      {/* Details grid */}
      <CardContent className="p-0">
        <div className="grid grid-cols-3 divide-x divide-border/50">
          <div className="flex items-center gap-3 p-5">
            <TrendingUp className="h-5 w-5 text-primary opacity-60" />
            <div>
              <p className="text-xs font-medium text-muted-foreground">
                Level
              </p>
              <p className="font-semibold tabular-nums">
                {result.overall_proficiency_level}/5
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3 p-5">
            <Clock className="h-5 w-5 text-primary opacity-60" />
            <div>
              <p className="text-xs font-medium text-muted-foreground">
                Time
              </p>
              <p className="font-semibold">
                {formatTime(result.total_time_seconds)}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3 p-5">
            <Calendar className="h-5 w-5 text-primary opacity-60" />
            <div>
              <p className="text-xs font-medium text-muted-foreground">
                Date
              </p>
              <p className="font-semibold">
                {new Date(result.created_at).toLocaleDateString(undefined, {
                  month: "short",
                  day: "numeric",
                  year: "numeric",
                })}
              </p>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
