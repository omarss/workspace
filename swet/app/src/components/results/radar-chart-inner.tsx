"use client";

import {
  Radar,
  RadarChart as RechartsRadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  ResponsiveContainer,
  Tooltip,
} from "recharts";
import type { RadarDataPoint } from "@/lib/types";

interface RadarChartInnerProps {
  data: RadarDataPoint[];
}

export function RadarChartInner({ data }: RadarChartInnerProps) {
  return (
    <ResponsiveContainer width="100%" height={380}>
      <RechartsRadarChart data={data} cx="50%" cy="50%" outerRadius="75%">
        <PolarGrid stroke="var(--color-border)" strokeOpacity={0.6} />
        <PolarAngleAxis
          dataKey="competency"
          tick={{ fontSize: 11, fill: "var(--color-muted-foreground)" }}
          tickFormatter={(value: string) =>
            value
              .replace("competency_", "")
              .replace(/_/g, " ")
              .replace(/\b\w/g, (c) => c.toUpperCase())
          }
        />
        <PolarRadiusAxis
          angle={90}
          domain={[0, 100]}
          tick={{ fontSize: 10, fill: "var(--color-muted-foreground)" }}
        />
        <Radar
          name="Score"
          dataKey="score"
          stroke="var(--color-primary)"
          fill="var(--color-primary)"
          fillOpacity={0.15}
          strokeWidth={2}
        />
        <Tooltip
          contentStyle={{
            backgroundColor: "var(--color-card)",
            border: "1px solid var(--color-border)",
            borderRadius: "0.75rem",
            fontSize: "0.875rem",
          }}
          formatter={(value: number) => [`${value.toFixed(1)}%`, "Score"]}
        />
      </RechartsRadarChart>
    </ResponsiveContainer>
  );
}
