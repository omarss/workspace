"use client";

import dynamic from "next/dynamic";
import { Loader2 } from "lucide-react";
import type { TrendDataPoint } from "@/lib/types";

// Lazy-load Recharts to avoid SSR issues
const TrendChartComponent = dynamic(
  () => import("./trend-chart-inner").then((mod) => mod.TrendChartInner),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-[280px] items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-primary" />
      </div>
    ),
  }
);

interface TrendChartProps {
  data: TrendDataPoint[];
}

export function TrendChart({ data }: TrendChartProps) {
  if (data.length < 2) {
    return (
      <div className="flex h-[280px] items-center justify-center text-sm text-muted-foreground">
        Complete at least 2 assessments to see your score trend.
      </div>
    );
  }

  return <TrendChartComponent data={data} />;
}
