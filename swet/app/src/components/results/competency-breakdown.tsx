"use client";

import { CompetencyCard } from "@/components/results/competency-card";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { CompetencyScore } from "@/lib/types";

interface CompetencyBreakdownProps {
  scores: CompetencyScore[];
}

export function CompetencyBreakdown({ scores }: CompetencyBreakdownProps) {
  if (scores.length === 0) {
    return null;
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Competency Breakdown</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {scores.map((score) => (
            <CompetencyCard key={score.competency_id} score={score} />
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
