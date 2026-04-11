"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { StatsSummary } from "@/components/results/stats-summary";
import { TrendChart } from "@/components/results/trend-chart";
import { HistoryList } from "@/components/results/history-list";
import {
  useHistory,
  useHistoryStats,
  useTrend,
} from "@/lib/api/hooks/use-results";

export default function HistoryPage() {
  const [page, setPage] = useState(1);
  const perPage = 10;

  const { data: historyData, isLoading } = useHistory({ page, per_page: perPage });
  const { data: stats } = useHistoryStats();
  const { data: trendData } = useTrend();

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-32">
        <Loader2 className="h-6 w-6 animate-spin text-primary" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {stats && <StatsSummary stats={stats} />}

      {trendData && (
        <Card>
          <CardHeader>
            <CardTitle>Score Trend</CardTitle>
          </CardHeader>
          <CardContent>
            <TrendChart data={trendData.data} />
          </CardContent>
        </Card>
      )}

      <HistoryList
        items={historyData?.items ?? []}
        totalCount={historyData?.total_count ?? 0}
        page={page}
        perPage={perPage}
        onPageChange={setPage}
      />
    </div>
  );
}
