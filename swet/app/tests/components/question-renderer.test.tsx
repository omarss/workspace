import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QuestionRenderer } from "@/components/assessment/question-renderer";
import type { AssessmentQuestion, QuestionFormat } from "@/lib/types";

function makeQuestion(
  format: QuestionFormat,
  overrides: Partial<AssessmentQuestion> = {}
): AssessmentQuestion {
  const base: AssessmentQuestion = {
    id: "test-q-1",
    competency_id: 1,
    format,
    difficulty: 3,
    title: `Test ${format} question`,
    body: `This is the body of a ${format} question.`,
    code_snippet: null,
    language: null,
    options: null,
    position: 0,
  };

  if (format === "mcq") {
    base.options = { A: "Option A", B: "Option B", C: "Option C", D: "Option D" };
  }

  if (format === "code_review" || format === "debugging") {
    base.code_snippet = 'def hello():\n    return "world"';
    base.language = "python";
  }

  return { ...base, ...overrides };
}

describe("QuestionRenderer", () => {
  it("renders MCQ with radio options", () => {
    const onChange = vi.fn();
    render(
      <QuestionRenderer
        question={makeQuestion("mcq")}
        value={undefined}
        onChange={onChange}
      />
    );

    expect(screen.getByText(/Option A/)).toBeDefined();
    expect(screen.getByText(/Option B/)).toBeDefined();
    expect(screen.getByText(/Option C/)).toBeDefined();
    expect(screen.getByText(/Option D/)).toBeDefined();
  });

  it("calls onChange when MCQ option selected", () => {
    const onChange = vi.fn();
    render(
      <QuestionRenderer
        question={makeQuestion("mcq")}
        value={undefined}
        onChange={onChange}
      />
    );

    const radioA = screen.getByRole("radio", { name: /A\s*Option A/i });
    fireEvent.click(radioA);
    expect(onChange).toHaveBeenCalledWith("A");
  });

  it("renders code review with textarea and code", () => {
    const onChange = vi.fn();
    render(
      <QuestionRenderer
        question={makeQuestion("code_review")}
        value=""
        onChange={onChange}
      />
    );

    expect(screen.getByLabelText("Your Review")).toBeDefined();
    // Code should be rendered (either highlighted or as fallback pre)
    expect(screen.getByText(/def hello/)).toBeDefined();
  });

  it("renders debugging with textarea and code", () => {
    const onChange = vi.fn();
    render(
      <QuestionRenderer
        question={makeQuestion("debugging")}
        value=""
        onChange={onChange}
      />
    );

    expect(screen.getByLabelText("Your Analysis")).toBeDefined();
  });

  it("renders short answer with textarea", () => {
    const onChange = vi.fn();
    render(
      <QuestionRenderer
        question={makeQuestion("short_answer")}
        value=""
        onChange={onChange}
      />
    );

    expect(screen.getByLabelText("Your Answer")).toBeDefined();
  });

  it("renders design prompt with textarea", () => {
    const onChange = vi.fn();
    render(
      <QuestionRenderer
        question={makeQuestion("design_prompt")}
        value=""
        onChange={onChange}
      />
    );

    expect(screen.getByLabelText("Your Design")).toBeDefined();
  });

  it("calls onChange on textarea input for text formats", () => {
    const onChange = vi.fn();
    render(
      <QuestionRenderer
        question={makeQuestion("short_answer")}
        value=""
        onChange={onChange}
      />
    );

    const textarea = screen.getByLabelText("Your Answer");
    fireEvent.change(textarea, { target: { value: "My answer text" } });
    expect(onChange).toHaveBeenCalledWith("My answer text");
  });

  it("shows character count for text formats", () => {
    render(
      <QuestionRenderer
        question={makeQuestion("code_review")}
        value="hello world"
        onChange={vi.fn()}
      />
    );

    expect(screen.getByText("11 characters")).toBeDefined();
  });

  it("shows error for unknown format", () => {
    render(
      <QuestionRenderer
        question={makeQuestion("mcq", { format: "unknown" as QuestionFormat })}
        value={undefined}
        onChange={vi.fn()}
      />
    );

    expect(screen.getByText(/Unknown question format/)).toBeDefined();
  });
});
