"use client";

import Link from "next/link";
import { ChevronLeft, ChevronRight, Clock } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import type { ResultSummary } from "@/lib/types";
import { cn } from "@/lib/utils";

const PROFICIENCY_BADGE: Record<string, string> = {
  novice: "bg-red-500/10 text-red-700 dark:text-red-300",
  beginner: "bg-orange-500/10 text-orange-700 dark:text-orange-300",
  intermediate: "bg-yellow-500/10 text-yellow-700 dark:text-yellow-300",
  advanced: "bg-blue-500/10 text-blue-700 dark:text-blue-300",
  expert: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
};

function formatTime(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  if (mins >= 60) {
    const hrs = Math.floor(mins / 60);
    return `${hrs}h ${mins % 60}m`;
  }
  return `${mins}m`;
}

interface HistoryListProps {
  items: ResultSummary[];
  totalCount: number;
  page: number;
  perPage: number;
  onPageChange: (page: number) => void;
}

export function HistoryList({
  items,
  totalCount,
  page,
  perPage,
  onPageChange,
}: HistoryListProps) {
  const totalPages = Math.ceil(totalCount / perPage);

  if (items.length === 0) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center gap-3 py-12 text-center">
          <div className="rounded-full bg-muted p-3">
            <Clock className="h-6 w-6 text-muted-foreground" />
          </div>
          <p className="text-muted-foreground">No assessments completed yet.</p>
          <Link href="/dashboard">
            <Button variant="outline">Start Your First Assessment</Button>
          </Link>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          Assessment History
          <span className="ml-2 text-sm font-normal text-muted-foreground">
            ({totalCount})
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {items.map((item) => {
          const badgeClass =
            PROFICIENCY_BADGE[item.proficiency_label] ?? "bg-muted text-muted-foreground";

          return (
            <Link
              key={item.id}
              href={`/results?id=${item.assessment_id}`}
              className="group block rounded-xl border border-border/60 p-4 transition-all hover:border-primary/20 hover:bg-accent/30 hover:shadow-sm"
            >
              <div className="flex items-center justify-between">
                <div className="min-w-0">
                  <p className="font-medium">
                    {new Date(item.created_at).toLocaleDateString(undefined, {
                      year: "numeric",
                      month: "short",
                      day: "numeric",
                    })}
                  </p>
                  <div className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
                    <Clock className="h-3 w-3" />
                    {formatTime(item.total_time_seconds)}
                    <span>&middot;</span>
                    <span
                      className={cn(
                        "rounded-full px-2 py-0.5 text-[10px] font-semibold capitalize",
                        badgeClass
                      )}
                    >
                      {item.proficiency_label}
                    </span>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <p className="text-2xl font-bold tabular-nums">
                    {item.overall_score.toFixed(1)}
                    <span className="text-sm font-normal text-muted-foreground">
                      %
                    </span>
                  </p>
                  <ChevronRight className="h-4 w-4 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
                </div>
              </div>
            </Link>
          );
        })}

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="flex items-center justify-center gap-2 pt-4">
            <Button
              variant="outline"
              size="sm"
              disabled={page <= 1}
              onClick={() => onPageChange(page - 1)}
            >
              <ChevronLeft className="h-4 w-4" />
              Previous
            </Button>
            <span className="px-2 text-sm tabular-nums text-muted-foreground">
              {page} / {totalPages}
            </span>
            <Button
              variant="outline"
              size="sm"
              disabled={page >= totalPages}
              onClick={() => onPageChange(page + 1)}
            >
              Next
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
