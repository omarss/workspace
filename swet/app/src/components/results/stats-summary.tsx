"use client";

import { Award, BarChart3, Target, Trophy } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import type { HistoryStats } from "@/lib/types";

interface StatsSummaryProps {
  stats: HistoryStats;
}

const STAT_ICONS = [BarChart3, Target, Trophy, Award];
const STAT_COLORS = [
  "bg-primary/10 text-primary",
  "bg-blue-500/10 text-blue-600 dark:text-blue-400",
  "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
  "bg-amber-500/10 text-amber-600 dark:text-amber-400",
];

export function StatsSummary({ stats }: StatsSummaryProps) {
  const items = [
    { label: "Assessments", value: String(stats.total_assessments) },
    { label: "Average Score", value: `${stats.average_score.toFixed(1)}%` },
    { label: "Highest Score", value: `${stats.highest_score.toFixed(1)}%` },
    {
      label: "Latest Level",
      value: stats.latest_proficiency_label,
      capitalize: true,
    },
  ];

  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {items.map((item, i) => {
        const Icon = STAT_ICONS[i];
        return (
          <Card key={item.label}>
            <CardContent className="flex items-center gap-4 p-5">
              <div
                className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl ${STAT_COLORS[i]}`}
              >
                <Icon className="h-5 w-5" />
              </div>
              <div>
                <p className="text-xs font-medium text-muted-foreground">
                  {item.label}
                </p>
                <p
                  className={`text-xl font-bold tabular-nums ${item.capitalize ? "capitalize" : ""}`}
                >
                  {item.value}
                </p>
              </div>
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}
