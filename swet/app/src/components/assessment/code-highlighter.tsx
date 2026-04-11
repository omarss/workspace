"use client";

import { useEffect, useState } from "react";
import { Copy, Check } from "lucide-react";
import type { BundledLanguage } from "shiki";

// Only load the languages we actually need to keep bundle size down
const SUPPORTED_LANGUAGES: BundledLanguage[] = [
  "python",
  "typescript",
  "javascript",
  "java",
  "go",
  "rust",
  "c",
  "cpp",
  "csharp",
  "ruby",
  "sql",
  "bash",
];

interface CodeHighlighterProps {
  code: string;
  language: string;
  className?: string;
}

export function CodeHighlighter({
  code,
  language,
  className,
}: CodeHighlighterProps) {
  const [html, setHtml] = useState<string>("");
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function highlight() {
      try {
        const { codeToHtml } = await import("shiki");
        const lang = SUPPORTED_LANGUAGES.includes(language as BundledLanguage)
          ? (language as BundledLanguage)
          : "text";

        const result = await codeToHtml(code, {
          lang,
          theme: "github-dark",
        });

        if (!cancelled) {
          setHtml(result);
        }
      } catch {
        // Fallback to plain text on any error
        if (!cancelled) {
          setHtml("");
        }
      }
    }

    highlight();
    return () => {
      cancelled = true;
    };
  }, [code, language]);

  function handleCopy() {
    navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  const langLabel = SUPPORTED_LANGUAGES.includes(language as BundledLanguage)
    ? language
    : "text";

  const wrapper = `group relative overflow-hidden rounded-xl border border-border/60 ${className ?? ""}`;

  const toolbar = (
    <div className="flex items-center justify-between border-b border-white/10 bg-zinc-800/80 px-4 py-2">
      <span
        className="text-[11px] font-medium uppercase tracking-wider text-zinc-400"
        style={{ fontFamily: "var(--font-mono)" }}
      >
        {langLabel}
      </span>
      <button
        type="button"
        onClick={handleCopy}
        className="flex items-center gap-1.5 rounded-md px-2 py-1 text-[11px] text-zinc-400 transition-colors hover:bg-white/10 hover:text-zinc-200"
        aria-label="Copy code"
      >
        {copied ? (
          <>
            <Check className="h-3 w-3 text-emerald-400" />
            Copied
          </>
        ) : (
          <>
            <Copy className="h-3 w-3" />
            Copy
          </>
        )}
      </button>
    </div>
  );

  // Fallback to plain pre while loading or on error
  if (!html) {
    return (
      <div className={wrapper}>
        {toolbar}
        <pre
          className="overflow-x-auto bg-zinc-900 p-4 text-sm leading-relaxed text-zinc-100"
          style={{ fontFamily: "var(--font-mono)" }}
        >
          <code>{code}</code>
        </pre>
      </div>
    );
  }

  return (
    <div className={wrapper}>
      {toolbar}
      <div
        className="overflow-x-auto text-sm leading-relaxed [&>pre]:bg-zinc-900 [&>pre]:p-4"
        style={{ fontFamily: "var(--font-mono)" }}
        dangerouslySetInnerHTML={{ __html: html }}
      />
    </div>
  );
}
