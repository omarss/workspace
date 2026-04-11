import Link from "next/link";
import { TryAnonymousButton } from "@/components/auth/try-anonymous-button";

export default function LandingPage() {
  return (
    <main className="flex min-h-screen flex-col">
      {/* Hero section */}
      <section className="relative flex flex-1 flex-col items-center justify-center overflow-hidden px-6 py-24">
        {/* Background decoration */}
        <div className="pointer-events-none absolute inset-0 overflow-hidden">
          <div className="absolute -top-48 left-1/2 h-96 w-96 -translate-x-1/2 rounded-full bg-primary/10 blur-3xl" />
          <div className="absolute -bottom-24 left-1/4 h-64 w-64 rounded-full bg-primary/5 blur-3xl" />
          <div className="absolute right-1/4 top-1/3 h-48 w-48 rounded-full bg-accent blur-3xl" />
        </div>

        <div className="relative z-10 mx-auto max-w-3xl text-center">
          {/* Badge */}
          <div className="mb-8 inline-flex items-center gap-2 rounded-full border border-primary/20 bg-primary/5 px-4 py-1.5 text-sm font-medium text-primary">
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-primary" />
            12 Core Competency Areas
          </div>

          <h1 className="mb-6 text-5xl font-bold tracking-tight sm:text-6xl lg:text-7xl">
            <span className="bg-gradient-to-r from-primary via-primary/80 to-primary/60 bg-clip-text text-transparent">
              SWET
            </span>
          </h1>

          <p className="mb-3 text-xl font-medium text-foreground/80 sm:text-2xl">
            Software Engineering Test
          </p>

          <p className="mx-auto mb-10 max-w-xl text-base leading-relaxed text-muted-foreground sm:text-lg">
            Professional-grade assessment platform that identifies and helps
            elevate software engineering competencies. Powered by AI-driven
            evaluation across multiple question formats.
          </p>

          <div className="flex flex-col items-center gap-4 sm:flex-row sm:justify-center">
            <Link
              href="/dashboard"
              className="inline-flex h-12 items-center justify-center rounded-xl bg-primary px-8 text-base font-medium text-primary-foreground shadow-lg shadow-primary/25 transition-all duration-200 hover:bg-primary/90 hover:shadow-xl hover:shadow-primary/30 active:scale-[0.98]"
            >
              Get Started
            </Link>
            <TryAnonymousButton />
          </div>
        </div>
      </section>

      {/* Feature highlights */}
      <section className="border-t border-border/50 bg-card/50 px-6 py-16">
        <div className="mx-auto grid max-w-5xl gap-8 sm:grid-cols-3">
          {[
            {
              title: "5 Question Formats",
              description:
                "MCQ, code review, debugging, short answer, and system design prompts for comprehensive evaluation.",
            },
            {
              title: "AI-Powered Grading",
              description:
                "Instant auto-grading for MCQ with Claude-powered evaluation for open-ended responses.",
            },
            {
              title: "Detailed Analytics",
              description:
                "Competency radar charts, score trends, and proficiency levels to track your growth over time.",
            },
          ].map((feature) => (
            <div key={feature.title} className="text-center sm:text-left">
              <h3 className="mb-2 font-semibold text-foreground">
                {feature.title}
              </h3>
              <p className="text-sm leading-relaxed text-muted-foreground">
                {feature.description}
              </p>
            </div>
          ))}
        </div>
      </section>
    </main>
  );
}
