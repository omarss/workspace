"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { PenLine } from "lucide-react";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import type { AssessmentQuestion } from "@/lib/types";

interface ShortAnswerRendererProps {
  question: AssessmentQuestion;
  value: string | undefined;
  onChange: (text: string) => void;
}

export function ShortAnswerRenderer({
  question,
  value,
  onChange,
}: ShortAnswerRendererProps) {
  const charCount = (value ?? "").length;

  return (
    <div className="space-y-6">
      <div className="prose prose-sm dark:prose-invert max-w-none">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>
          {question.body}
        </ReactMarkdown>
      </div>

      <div className="space-y-2">
        <Label htmlFor="short-answer-response" className="flex items-center gap-2">
          <PenLine className="h-4 w-4" />
          Your Answer
        </Label>
        <Textarea
          id="short-answer-response"
          placeholder="Write your answer here (aim for 100-300 words)..."
          value={value ?? ""}
          onChange={(e) => onChange(e.target.value)}
          rows={10}
          className="min-h-[180px] rounded-xl"
        />
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>{charCount} characters</span>
          {charCount > 0 && charCount < 50 && (
            <span className="text-amber-600 dark:text-amber-400">
              Consider adding more detail
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
