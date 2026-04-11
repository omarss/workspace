"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Layers } from "lucide-react";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import type { AssessmentQuestion } from "@/lib/types";

interface DesignPromptRendererProps {
  question: AssessmentQuestion;
  value: string | undefined;
  onChange: (text: string) => void;
}

export function DesignPromptRenderer({
  question,
  value,
  onChange,
}: DesignPromptRendererProps) {
  const charCount = (value ?? "").length;

  return (
    <div className="space-y-6">
      <div className="prose prose-sm dark:prose-invert max-w-none">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>
          {question.body}
        </ReactMarkdown>
      </div>

      <div className="space-y-2">
        <Label htmlFor="design-response" className="flex items-center gap-2">
          <Layers className="h-4 w-4" />
          Your Design
        </Label>
        <div className="flex flex-wrap gap-2 text-[11px] text-muted-foreground">
          {["Architecture", "Data Model", "Trade-offs", "Scalability"].map(
            (topic) => (
              <span
                key={topic}
                className="rounded-full border border-border/60 px-2.5 py-0.5"
              >
                {topic}
              </span>
            )
          )}
        </div>
        <Textarea
          id="design-response"
          placeholder={[
            "## Architecture",
            "Describe your high-level system architecture...",
            "",
            "## Data Model",
            "Define core entities and relationships...",
            "",
            "## Trade-offs",
            "Discuss key design decisions...",
            "",
            "## Scalability",
            "How does your design handle growth...",
          ].join("\n")}
          value={value ?? ""}
          onChange={(e) => onChange(e.target.value)}
          rows={16}
          className="min-h-[300px] rounded-xl"
        />
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>{charCount} characters</span>
          {charCount > 0 && charCount < 200 && (
            <span className="text-amber-600 dark:text-amber-400">
              Consider addressing all sections
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
