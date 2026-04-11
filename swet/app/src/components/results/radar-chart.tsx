"use client";

import dynamic from "next/dynamic";
import { Loader2 } from "lucide-react";
import type { RadarDataPoint } from "@/lib/types";

// Lazy-load Recharts to avoid SSR issues
const RadarChartComponent = dynamic(
  () => import("./radar-chart-inner").then((mod) => mod.RadarChartInner),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-[380px] items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-primary" />
      </div>
    ),
  }
);

interface RadarChartProps {
  data: RadarDataPoint[];
}

export function RadarChart({ data }: RadarChartProps) {
  if (data.length === 0) {
    return (
      <div className="flex h-[380px] items-center justify-center text-sm text-muted-foreground">
        No competency data available.
      </div>
    );
  }

  return <RadarChartComponent data={data} />;
}
