"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { FileCode2, MessageSquare } from "lucide-react";
import { CodeHighlighter } from "./code-highlighter";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import type { AssessmentQuestion } from "@/lib/types";

interface CodeReviewRendererProps {
  question: AssessmentQuestion;
  value: string | undefined;
  onChange: (text: string) => void;
}

export function CodeReviewRenderer({
  question,
  value,
  onChange,
}: CodeReviewRendererProps) {
  const charCount = (value ?? "").length;

  return (
    <div className="space-y-6">
      <div className="prose prose-sm dark:prose-invert max-w-none">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>
          {question.body}
        </ReactMarkdown>
      </div>

      {question.code_snippet && (
        <div className="space-y-2">
          <Label className="flex items-center gap-2 text-muted-foreground">
            <FileCode2 className="h-4 w-4" />
            Code to review
            {question.language && (
              <span className="rounded-md bg-muted px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider">
                {question.language}
              </span>
            )}
          </Label>
          <CodeHighlighter
            code={question.code_snippet}
            language={question.language ?? "text"}
          />
        </div>
      )}

      <div className="space-y-2">
        <Label htmlFor="review-response" className="flex items-center gap-2">
          <MessageSquare className="h-4 w-4" />
          Your Review
        </Label>
        <Textarea
          id="review-response"
          placeholder="Identify issues, suggest improvements, and explain your reasoning..."
          value={value ?? ""}
          onChange={(e) => onChange(e.target.value)}
          rows={12}
          className="min-h-[200px] rounded-xl"
        />
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>{charCount} characters</span>
          {charCount > 0 && charCount < 100 && (
            <span className="text-amber-600 dark:text-amber-400">
              Consider adding more detail
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
