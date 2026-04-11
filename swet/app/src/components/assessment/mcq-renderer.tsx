"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { cn } from "@/lib/utils";
import type { AssessmentQuestion } from "@/lib/types";

interface MCQRendererProps {
  question: AssessmentQuestion;
  value: string | undefined;
  onChange: (option: string) => void;
}

export function MCQRenderer({ question, value, onChange }: MCQRendererProps) {
  const options = question.options ?? {};

  return (
    <div className="space-y-6">
      <div className="prose prose-sm dark:prose-invert max-w-none">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>
          {question.body}
        </ReactMarkdown>
      </div>

      <RadioGroup
        value={value ?? ""}
        onValueChange={onChange}
        className="grid gap-3"
      >
        {Object.entries(options).map(([key, text]) => {
          const isSelected = value === key;
          return (
            <div
              key={key}
              className={cn(
                "flex items-start gap-3 rounded-xl border p-4 transition-all cursor-pointer",
                isSelected
                  ? "border-primary bg-primary/5 shadow-sm shadow-primary/10"
                  : "border-border/60 hover:border-primary/30 hover:bg-accent/30"
              )}
              onClick={() => onChange(key)}
            >
              <RadioGroupItem
                value={key}
                id={`option-${key}`}
                className="mt-0.5 shrink-0"
              />
              <Label
                htmlFor={`option-${key}`}
                className="flex-1 cursor-pointer font-normal leading-relaxed"
              >
                <span className="mr-2 inline-flex h-6 w-6 items-center justify-center rounded-md bg-muted text-xs font-bold">
                  {key}
                </span>
                {text}
              </Label>
            </div>
          );
        })}
      </RadioGroup>
    </div>
  );
}
