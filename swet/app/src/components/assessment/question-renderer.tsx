"use client";

import { AlertTriangle } from "lucide-react";
import type { AssessmentQuestion } from "@/lib/types";
import { MCQRenderer } from "./mcq-renderer";
import { CodeReviewRenderer } from "./code-review-renderer";
import { DebuggingRenderer } from "./debugging-renderer";
import { ShortAnswerRenderer } from "./short-answer-renderer";
import { DesignPromptRenderer } from "./design-prompt-renderer";

interface QuestionRendererProps {
  question: AssessmentQuestion;
  /** For MCQ: the selected option letter. For others: the response text. */
  value: string | undefined;
  /** Callback when the answer changes. */
  onChange: (value: string) => void;
}

/**
 * Dispatches to the correct format-specific renderer based on question.format.
 * All renderers are fully controlled (value/onChange).
 */
export function QuestionRenderer({
  question,
  value,
  onChange,
}: QuestionRendererProps) {
  switch (question.format) {
    case "mcq":
      return (
        <MCQRenderer question={question} value={value} onChange={onChange} />
      );
    case "code_review":
      return (
        <CodeReviewRenderer
          question={question}
          value={value}
          onChange={onChange}
        />
      );
    case "debugging":
      return (
        <DebuggingRenderer
          question={question}
          value={value}
          onChange={onChange}
        />
      );
    case "short_answer":
      return (
        <ShortAnswerRenderer
          question={question}
          value={value}
          onChange={onChange}
        />
      );
    case "design_prompt":
      return (
        <DesignPromptRenderer
          question={question}
          value={value}
          onChange={onChange}
        />
      );
    default:
      return (
        <div className="flex items-center gap-3 rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
          <AlertTriangle className="h-5 w-5 shrink-0" />
          Unknown question format: <code className="font-mono">{question.format}</code>
        </div>
      );
  }
}
