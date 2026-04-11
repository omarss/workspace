"use client";

import { useSearchParams } from "next/navigation";
import { Loader2 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ResultSummary } from "@/components/results/result-summary";
import { RadarChart } from "@/components/results/radar-chart";
import { CompetencyBreakdown } from "@/components/results/competency-breakdown";
import { GradingProgress } from "@/components/results/grading-progress";
import { useResult, useRadarData } from "@/lib/api/hooks/use-results";

export default function ResultsPage() {
  const searchParams = useSearchParams();
  const assessmentId = searchParams.get("id");

  const { data: result, isLoading } = useResult(assessmentId ?? "");
  const { data: radarData } = useRadarData(assessmentId ?? "");

  if (!assessmentId) {
    return (
      <Card>
        <CardContent className="p-8 text-center text-muted-foreground">
          No assessment ID provided. View results from the history page.
        </CardContent>
      </Card>
    );
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-32">
        <Loader2 className="h-6 w-6 animate-spin text-primary" />
      </div>
    );
  }

  if (!result) {
    return (
      <Card>
        <CardContent className="p-8 text-center text-muted-foreground">
          Results not found for this assessment.
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      <GradingProgress assessmentId={assessmentId} />
      <ResultSummary result={result} />

      <Card>
        <CardHeader>
          <CardTitle>Competency Radar</CardTitle>
        </CardHeader>
        <CardContent>
          <RadarChart data={radarData?.data ?? []} />
        </CardContent>
      </Card>

      <CompetencyBreakdown scores={result.competency_scores} />
    </div>
  );
}
