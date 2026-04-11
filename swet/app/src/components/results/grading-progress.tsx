"use client";

import { Loader2 } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { useGradingStatus } from "@/lib/api/hooks/use-results";

interface GradingProgressProps {
  assessmentId: string;
}

export function GradingProgress({ assessmentId }: GradingProgressProps) {
  const { data } = useGradingStatus(assessmentId);

  if (!data || data.grading_status === "complete") {
    return null;
  }

  return (
    <Card className="border-primary/20 bg-primary/5">
      <CardContent className="flex items-center gap-3 p-5">
        <Loader2 className="h-5 w-5 animate-spin text-primary" />
        <div>
          <p className="text-sm font-semibold text-foreground">
            Grading in progress
          </p>
          <p className="text-xs text-muted-foreground">
            AI is evaluating your open-ended answers. Results will update automatically.
          </p>
        </div>
      </CardContent>
    </Card>
  );
}
