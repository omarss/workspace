"use client";

import { useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useSession } from "next-auth/react";
import {
  ArrowRight,
  BarChart3,
  ClipboardCheck,
  History,
  Loader2,
  Play,
  Settings,
  Sparkles,
  Trophy,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  useAssessments,
  useCreateAssessment,
  usePoolStatus,
  useGeneratePools,
} from "@/lib/api/hooks/use-assessments";
import { SignInButton } from "@/components/auth/sign-in-button";
import { TryAnonymousButton } from "@/components/auth/try-anonymous-button";
import { useAnonymousStore } from "@/lib/stores/anonymous-store";

export default function DashboardPage() {
  const router = useRouter();
  const { data: session, status } = useSession();
  const anonToken = useAnonymousStore((s) => s.token);
  const hydrate = useAnonymousStore((s) => s.hydrate);
  const { data: assessmentData } = useAssessments();
  const { data: poolStatus } = usePoolStatus();
  const generatePools = useGeneratePools();
  const createAssessment = useCreateAssessment();

  useEffect(() => {
    hydrate();
  }, [hydrate]);

  const isAuthenticated = !!session || !!anonToken;

  if (status === "loading") {
    return (
      <div className="flex items-center justify-center py-32">
        <Loader2 className="h-6 w-6 animate-spin text-primary" />
      </div>
    );
  }

  if (!isAuthenticated) {
    return (
      <div className="flex flex-col items-center justify-center gap-4 py-32">
        <div className="rounded-full bg-primary/10 p-4">
          <ClipboardCheck className="h-8 w-8 text-primary" />
        </div>
        <h2 className="text-2xl font-bold">Sign in to continue</h2>
        <p className="text-muted-foreground">
          Access your assessments and track your progress
        </p>
        <div className="mt-2 flex flex-col items-center gap-3 sm:flex-row">
          <SignInButton />
          <TryAnonymousButton />
        </div>
      </div>
    );
  }

  const displayName =
    session?.user?.name || (anonToken ? "Anonymous" : "engineer");
  const completedCount =
    assessmentData?.assessments.filter((a) => a.status === "completed")
      .length ?? 0;
  const inProgressAssessment = assessmentData?.assessments.find(
    (a) => a.status === "in_progress"
  );

  // Pool generation state
  const poolsReady = poolStatus?.ready ?? false;
  const isGenerating =
    generatePools.isPending || (poolStatus?.generating ?? false);
  const poolsTotal = poolStatus?.total ?? 0;
  const poolsComplete = poolStatus?.pools.complete ?? 0;
  const poolsFailed = poolStatus?.pools.failed ?? 0;
  const poolsProgress = poolsTotal > 0 ? Math.round((poolsComplete / poolsTotal) * 100) : 0;

  function handleGenerateOrStart() {
    if (!poolsReady) {
      // Trigger generation — the polling in usePoolStatus will track progress
      generatePools.mutate();
    } else {
      // Pools are ready, create assessment and navigate
      createAssessment.mutate(
        { is_timed: true, time_limit_minutes: 60 },
        {
          onSuccess: (assessment) => {
            router.push(`/assessment?id=${assessment.id}`);
          },
        }
      );
    }
  }

  return (
    <div className="space-y-8">
      {/* Welcome header */}
      <div>
        <h1 className="text-3xl font-bold tracking-tight">
          Welcome back, {displayName}
        </h1>
        <p className="mt-1 text-muted-foreground">
          Here&apos;s an overview of your assessment journey
        </p>
      </div>

      {/* Stats cards */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {/* Completed */}
        <Card>
          <CardContent className="flex items-center gap-4 p-6">
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-success/10">
              <Trophy className="h-6 w-6 text-success" />
            </div>
            <div>
              <p className="text-sm font-medium text-muted-foreground">
                Completed
              </p>
              <p className="text-3xl font-bold tabular-nums">
                {completedCount}
              </p>
            </div>
          </CardContent>
        </Card>

        {/* Current Assessment */}
        <Card>
          <CardContent className="flex items-center gap-4 p-6">
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-primary/10">
              <BarChart3 className="h-6 w-6 text-primary" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-muted-foreground">
                Current
              </p>
              <p className="truncate text-lg font-semibold">
                {inProgressAssessment ? "In Progress" : "None"}
              </p>
            </div>
            {inProgressAssessment && (
              <Link href={`/assessment?id=${inProgressAssessment.id}`}>
                <Button size="sm">
                  <Play className="h-3.5 w-3.5" />
                  Continue
                </Button>
              </Link>
            )}
          </CardContent>
        </Card>

        {/* Generate / Start New */}
        <Card className="border-dashed border-primary/30 bg-primary/[0.02]">
          <CardContent className="flex flex-col gap-4 p-6">
            <div className="flex items-center gap-4">
              <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl border-2 border-dashed border-primary/30">
                {isGenerating ? (
                  <Sparkles className="h-6 w-6 animate-pulse text-primary" />
                ) : (
                  <ClipboardCheck className="h-6 w-6 text-primary/60" />
                )}
              </div>
              <div className="min-w-0 flex-1">
                <p className="font-semibold">
                  {isGenerating
                    ? "Generating Questions..."
                    : poolsReady
                      ? "New Assessment"
                      : "Generate Questions"}
                </p>
                <p className="text-sm text-muted-foreground">
                  {isGenerating
                    ? `${poolsProgress}% complete`
                    : poolsReady
                      ? "Questions ready — start anytime"
                      : "AI-powered questions tailored to your profile"}
                </p>
              </div>
              <Button
                size="sm"
                variant={poolsReady ? "outline" : "default"}
                onClick={handleGenerateOrStart}
                disabled={isGenerating || createAssessment.isPending}
              >
                {isGenerating || createAssessment.isPending ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : poolsReady ? (
                  <>
                    Start
                    <ArrowRight className="h-3.5 w-3.5" />
                  </>
                ) : (
                  <>
                    Generate
                    <Sparkles className="h-3.5 w-3.5" />
                  </>
                )}
              </Button>
            </div>

            {/* Progress bar during generation */}
            {isGenerating && (
              <div className="space-y-1">
                <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
                  <div
                    className="h-full rounded-full bg-gradient-to-r from-primary to-primary/80 transition-all duration-500"
                    style={{ width: `${Math.max(poolsProgress, 3)}%` }}
                  />
                </div>
                <p className="text-[11px] text-muted-foreground">
                  {poolsComplete} / {poolsTotal} question pools generated
                  {poolsFailed > 0 && (
                    <span className="text-amber-600 dark:text-amber-400">
                      {" "}({poolsFailed} failed — will retry)
                    </span>
                  )}
                </p>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Quick actions */}
      <div>
        <h2 className="mb-4 text-lg font-semibold">Quick Actions</h2>
        <div className="grid gap-3 sm:grid-cols-2">
          <Link href="/history">
            <Card className="group cursor-pointer transition-colors hover:border-primary/20 hover:bg-accent/30">
              <CardContent className="flex items-center gap-3 p-5">
                <History className="h-5 w-5 text-muted-foreground group-hover:text-primary" />
                <div>
                  <p className="font-medium">View History</p>
                  <p className="text-sm text-muted-foreground">
                    Review past assessments and track trends
                  </p>
                </div>
                <ArrowRight className="ml-auto h-4 w-4 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
              </CardContent>
            </Card>
          </Link>
          <Link href="/onboarding">
            <Card className="group cursor-pointer transition-colors hover:border-primary/20 hover:bg-accent/30">
              <CardContent className="flex items-center gap-3 p-5">
                <Settings className="h-5 w-5 text-muted-foreground group-hover:text-primary" />
                <div>
                  <p className="font-medium">Update Profile</p>
                  <p className="text-sm text-muted-foreground">
                    Change your role and technology preferences
                  </p>
                </div>
                <ArrowRight className="ml-auto h-4 w-4 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
              </CardContent>
            </Card>
          </Link>
        </div>
      </div>
    </div>
  );
}
