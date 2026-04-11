"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Bug, Wrench } from "lucide-react";
import { CodeHighlighter } from "./code-highlighter";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import type { AssessmentQuestion } from "@/lib/types";

interface DebuggingRendererProps {
  question: AssessmentQuestion;
  value: string | undefined;
  onChange: (text: string) => void;
}

export function DebuggingRenderer({
  question,
  value,
  onChange,
}: DebuggingRendererProps) {
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
            <Bug className="h-4 w-4" />
            Code and error output
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
        <Label htmlFor="debug-response" className="flex items-center gap-2">
          <Wrench className="h-4 w-4" />
          Your Analysis
        </Label>
        <Textarea
          id="debug-response"
          placeholder={[
            "## Root Cause",
            "Describe the root cause of the issue...",
            "",
            "## Fix",
            "Provide your fix with corrected code...",
            "",
            "## Prevention",
            "Suggest measures to prevent recurrence...",
          ].join("\n")}
          value={value ?? ""}
          onChange={(e) => onChange(e.target.value)}
          rows={14}
          className="min-h-[250px] rounded-xl"
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
