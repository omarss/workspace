"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useDebouncedCallback } from "use-debounce";
import { Loader2 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { QuestionRenderer } from "@/components/assessment/question-renderer";
import { QuestionGrid } from "@/components/assessment/question-grid";
import { NavButtons } from "@/components/assessment/nav-buttons";
import { TimerDisplay } from "@/components/assessment/timer-display";
import { ProgressBar } from "@/components/assessment/progress-bar";
import { SaveIndicator } from "@/components/assessment/save-indicator";
import { FinishDialog } from "@/components/assessment/finish-dialog";
import { useAssessmentStore } from "@/lib/stores/assessment-store";
import { useTimerStore } from "@/lib/stores/timer-store";
import {
  useAssessmentQuestions,
  useSubmitAnswer,
  useCompleteAssessment,
} from "@/lib/api/hooks/use-assessments";

const FORMAT_LABELS: Record<string, { label: string; color: string }> = {
  mcq: { label: "Multiple Choice", color: "bg-blue-500/10 text-blue-700 dark:text-blue-300" },
  code_review: { label: "Code Review", color: "bg-purple-500/10 text-purple-700 dark:text-purple-300" },
  debugging: { label: "Debugging", color: "bg-red-500/10 text-red-700 dark:text-red-300" },
  short_answer: { label: "Short Answer", color: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300" },
  design_prompt: { label: "System Design", color: "bg-amber-500/10 text-amber-700 dark:text-amber-300" },
};

export default function AssessmentPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const assessmentId = searchParams.get("id");

  const [showFinish, setShowFinish] = useState(false);

  // Stores
  const currentIndex = useAssessmentStore((s) => s.currentIndex);
  const answers = useAssessmentStore((s) => s.answers);
  const flaggedQuestions = useAssessmentStore((s) => s.flaggedQuestions);
  const setCurrentIndex = useAssessmentStore((s) => s.setCurrentIndex);
  const saveAnswer = useAssessmentStore((s) => s.saveAnswer);
  const setSaveStatus = useAssessmentStore((s) => s.setSaveStatus);
  const setAssessment = useAssessmentStore((s) => s.setAssessment);

  const timerStart = useTimerStore((s) => s.start);
  const questionElapsed = useTimerStore((s) => s.questionElapsed);
  const resetQuestion = useTimerStore((s) => s.resetQuestion);

  // API
  const { data: questions, isLoading } = useAssessmentQuestions(assessmentId ?? "");
  const submitAnswer = useSubmitAnswer(assessmentId ?? "");
  const completeAssessment = useCompleteAssessment(assessmentId ?? "");

  // Initialize assessment
  useEffect(() => {
    if (assessmentId) {
      setAssessment(assessmentId);
      timerStart();
    }
  }, [assessmentId, setAssessment, timerStart]);

  // Current question
  const currentQuestion = questions?.[currentIndex];
  const currentQuestionId = currentQuestion?.id;

  // Answer value for current question
  const currentAnswer = currentQuestionId ? answers[currentQuestionId] : undefined;
  const currentValue = currentQuestion?.format === "mcq"
    ? currentAnswer?.option
    : currentAnswer?.text;

  // Set of answered question IDs
  const answeredIds = useMemo(
    () => new Set(Object.keys(answers)),
    [answers]
  );
  const questionIds = useMemo(
    () => (questions ?? []).map((q) => q.id),
    [questions]
  );

  // Debounced auto-save for text inputs (800ms)
  const debouncedSave = useDebouncedCallback(
    (questionId: string, text: string) => {
      setSaveStatus("saving");
      submitAnswer.mutate(
        {
          question_id: questionId,
          response_text: text,
          time_spent_seconds: questionElapsed,
          is_auto_saved: true,
        },
        {
          onSuccess: () => setSaveStatus("saved"),
          onError: () => setSaveStatus("error"),
        }
      );
    },
    800
  );

  // Handle answer change
  const handleChange = useCallback(
    (value: string) => {
      if (!currentQuestion) return;

      const isMCQ = currentQuestion.format === "mcq";
      const answerData = isMCQ
        ? { option: value, timeSpent: questionElapsed }
        : { text: value, timeSpent: questionElapsed };

      saveAnswer(currentQuestion.id, answerData);

      if (isMCQ) {
        setSaveStatus("saving");
        submitAnswer.mutate(
          {
            question_id: currentQuestion.id,
            selected_option: value,
            time_spent_seconds: questionElapsed,
            is_auto_saved: true,
          },
          {
            onSuccess: () => setSaveStatus("saved"),
            onError: () => setSaveStatus("error"),
          }
        );
      } else {
        debouncedSave(currentQuestion.id, value);
      }
    },
    [currentQuestion, questionElapsed, saveAnswer, setSaveStatus, submitAnswer, debouncedSave]
  );

  // Navigate to a question
  const handleNavigate = useCallback(
    (index: number) => {
      if (index >= 0 && index < (questions?.length ?? 0)) {
        setCurrentIndex(index);
        resetQuestion();
      }
    },
    [questions?.length, setCurrentIndex, resetQuestion]
  );

  // Handle keyboard shortcuts
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.target instanceof HTMLTextAreaElement) return;

      if (e.key === "ArrowLeft") {
        handleNavigate(currentIndex - 1);
      } else if (e.key === "ArrowRight") {
        handleNavigate(currentIndex + 1);
      } else if (e.key === "f" || e.key === "F") {
        useAssessmentStore.getState().toggleFlag(currentIndex);
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [currentIndex, handleNavigate]);

  // Finish assessment
  const handleFinish = useCallback(() => {
    completeAssessment.mutate(undefined, {
      onSuccess: () => {
        useAssessmentStore.getState().reset();
        useTimerStore.getState().reset();
        router.push(`/results?id=${assessmentId}`);
      },
    });
  }, [completeAssessment, assessmentId, router]);

  // Auto-submit on time expired
  const handleTimeExpired = useCallback(() => {
    handleFinish();
  }, [handleFinish]);

  if (!assessmentId) {
    return (
      <Card>
        <CardContent className="p-8 text-center text-muted-foreground">
          No assessment ID provided. Start an assessment from the dashboard.
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

  if (!questions || questions.length === 0) {
    return (
      <Card>
        <CardContent className="p-8 text-center text-muted-foreground">
          No questions found for this assessment.
        </CardContent>
      </Card>
    );
  }

  const formatInfo = FORMAT_LABELS[currentQuestion?.format ?? ""] ?? {
    label: currentQuestion?.format,
    color: "bg-muted text-muted-foreground",
  };

  return (
    <div className="flex gap-6">
      {/* Sidebar: question grid (hidden on mobile) */}
      <aside className="hidden w-80 shrink-0 lg:block">
        <Card className="sticky top-24">
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">
              Questions
            </CardTitle>
          </CardHeader>
          <CardContent>
            <QuestionGrid
              total={questions.length}
              answeredIds={answeredIds}
              questionIds={questionIds}
              onNavigate={handleNavigate}
            />
          </CardContent>
        </Card>
      </aside>

      {/* Main content */}
      <main className="min-w-0 flex-1">
        {/* Top bar */}
        <div className="mb-5 flex flex-wrap items-center gap-4">
          <TimerDisplay onTimeExpired={handleTimeExpired} />
          <ProgressBar
            current={answeredIds.size}
            total={questions.length}
            className="flex-1"
          />
          <SaveIndicator />
        </div>

        {/* Question card */}
        <Card className="overflow-hidden">
          <CardHeader className="bg-muted/30 pb-4">
            <div className="flex items-center justify-between gap-3">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                Question {currentIndex + 1} of {questions.length}
              </CardTitle>
              <span
                className={`rounded-full px-3 py-1 text-xs font-semibold ${formatInfo.color}`}
              >
                {formatInfo.label}
              </span>
            </div>
            {currentQuestion && (
              <h2 className="mt-2 text-lg font-semibold leading-snug">
                {currentQuestion.title}
              </h2>
            )}
          </CardHeader>
          <CardContent className="pt-6">
            {currentQuestion && (
              <QuestionRenderer
                question={currentQuestion}
                value={currentValue}
                onChange={handleChange}
              />
            )}
          </CardContent>
        </Card>

        {/* Navigation */}
        <NavButtons
          total={questions.length}
          onNavigate={handleNavigate}
          onFinish={() => setShowFinish(true)}
          className="mt-5"
        />
      </main>

      {/* Finish dialog */}
      <FinishDialog
        open={showFinish}
        onOpenChange={setShowFinish}
        onConfirm={handleFinish}
        totalQuestions={questions.length}
        answeredCount={answeredIds.size}
        flaggedCount={flaggedQuestions.size}
        isSubmitting={completeAssessment.isPending}
      />
    </div>
  );
}
