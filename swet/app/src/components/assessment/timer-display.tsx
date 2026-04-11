"use client";

import { useEffect } from "react";
import { Clock, Pause, Play } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useTimerStore } from "@/lib/stores/timer-store";
import { cn } from "@/lib/utils";

function formatTime(seconds: number): string {
  const hrs = Math.floor(seconds / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  const secs = seconds % 60;

  if (hrs > 0) {
    return `${hrs}:${mins.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
  }
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}

interface TimerDisplayProps {
  /** Called when time expires (for auto-submit) */
  onTimeExpired?: () => void;
}

export function TimerDisplay({ onTimeExpired }: TimerDisplayProps) {
  const {
    totalElapsed,
    isRunning,
    timeLimit,
    autoSubmitTriggered,
    getTimeRemaining,
    getWarningLevel,
    tick,
    start,
    pause,
    setAutoSubmitTriggered,
  } = useTimerStore();

  const remaining = getTimeRemaining();
  const warningLevel = getWarningLevel();
  const isCountdown = timeLimit !== null;
  const displayTime = isCountdown && remaining !== null ? remaining : totalElapsed;

  // Timer tick effect
  useEffect(() => {
    if (!isRunning) return;
    const interval = setInterval(tick, 1000);
    return () => clearInterval(interval);
  }, [isRunning, tick]);

  // Auto-pause on tab hidden
  useEffect(() => {
    function handleVisibility() {
      if (document.hidden) {
        pause();
      } else {
        start();
      }
    }
    document.addEventListener("visibilitychange", handleVisibility);
    return () => document.removeEventListener("visibilitychange", handleVisibility);
  }, [pause, start]);

  // Auto-submit when time expires
  useEffect(() => {
    if (remaining !== null && remaining <= 0 && !autoSubmitTriggered && onTimeExpired) {
      setAutoSubmitTriggered();
      onTimeExpired();
    }
  }, [remaining, autoSubmitTriggered, onTimeExpired, setAutoSubmitTriggered]);

  return (
    <div
      role="timer"
      aria-label={isCountdown ? "Time remaining" : "Time elapsed"}
      className={cn(
        "flex items-center gap-2.5 rounded-xl border px-4 py-2.5 text-sm transition-all",
        warningLevel === "red" &&
          "border-red-400/50 bg-red-500/10 text-red-600 shadow-sm shadow-red-500/10 animate-pulse dark:text-red-400",
        warningLevel === "amber" &&
          "border-amber-400/50 bg-amber-500/10 text-amber-600 shadow-sm shadow-amber-500/10 dark:text-amber-400",
        warningLevel === "normal" && "border-border bg-card"
      )}
    >
      <Clock className="h-4 w-4 opacity-60" />
      <span className="min-w-[3.5rem] font-[family-name:var(--font-mono)] font-medium tabular-nums">
        {formatTime(displayTime)}
      </span>
      <Button
        variant="ghost"
        size="icon"
        className="h-7 w-7"
        onClick={() => (isRunning ? pause() : start())}
        aria-label={isRunning ? "Pause timer" : "Resume timer"}
      >
        {isRunning ? (
          <Pause className="h-3.5 w-3.5" />
        ) : (
          <Play className="h-3.5 w-3.5" />
        )}
      </Button>
    </div>
  );
}
