"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Check, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  useOnboardingOptions,
  useCreateProfile,
} from "@/lib/api/hooks/use-onboarding";
import { cn } from "@/lib/utils";

type Step = "role" | "technologies" | "confirm";

const STEPS: { key: Step; label: string }[] = [
  { key: "role", label: "Role" },
  { key: "technologies", label: "Technologies" },
  { key: "confirm", label: "Confirm" },
];

export default function OnboardingPage() {
  const router = useRouter();
  const { data: options, isLoading } = useOnboardingOptions();
  const createProfile = useCreateProfile();

  const [step, setStep] = useState<Step>("role");
  const [selectedRole, setSelectedRole] = useState("");
  const [selectedInterests] = useState<string[]>([]);
  const [selectedLanguages, setSelectedLanguages] = useState<string[]>([]);
  const [selectedFrameworks, setSelectedFrameworks] = useState<string[]>([]);

  if (isLoading || !options) {
    return (
      <div className="flex items-center justify-center py-32">
        <Loader2 className="h-6 w-6 animate-spin text-primary" />
      </div>
    );
  }

  const stepIndex = STEPS.findIndex((s) => s.key === step);

  const toggleItem = (
    item: string,
    list: string[],
    setter: (v: string[]) => void
  ) => {
    setter(
      list.includes(item) ? list.filter((i) => i !== item) : [...list, item]
    );
  };

  const handleSubmit = async () => {
    await createProfile.mutateAsync({
      primary_role: selectedRole,
      interests: selectedInterests,
      technologies: {
        languages: selectedLanguages,
        frameworks: selectedFrameworks,
      },
    });
    router.push("/dashboard");
  };

  return (
    <div className="mx-auto max-w-2xl space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold tracking-tight">
          Set Up Your Profile
        </h1>
        <p className="mt-1 text-muted-foreground">
          Personalize your assessment experience
        </p>
      </div>

      {/* Step indicator */}
      <div className="flex items-center gap-3">
        {STEPS.map((s, i) => (
          <div key={s.key} className="flex items-center gap-3">
            {i > 0 && (
              <div
                className={cn(
                  "h-px w-8 transition-colors sm:w-12",
                  i <= stepIndex ? "bg-primary" : "bg-border"
                )}
              />
            )}
            <div className="flex items-center gap-2">
              <div
                className={cn(
                  "flex h-8 w-8 items-center justify-center rounded-full text-xs font-semibold transition-all",
                  i < stepIndex
                    ? "bg-primary text-primary-foreground"
                    : i === stepIndex
                      ? "bg-primary text-primary-foreground shadow-md shadow-primary/25"
                      : "bg-muted text-muted-foreground"
                )}
              >
                {i < stepIndex ? (
                  <Check className="h-4 w-4" />
                ) : (
                  i + 1
                )}
              </div>
              <span
                className={cn(
                  "hidden text-sm font-medium sm:inline",
                  i === stepIndex
                    ? "text-foreground"
                    : "text-muted-foreground"
                )}
              >
                {s.label}
              </span>
            </div>
          </div>
        ))}
      </div>

      {/* Step 1: Role */}
      {step === "role" && (
        <Card>
          <CardHeader>
            <CardTitle>Select Your Primary Role</CardTitle>
            <CardDescription>
              This determines the competency weights in your assessment
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
              {options.roles.map((role) => (
                <button
                  key={role}
                  onClick={() => setSelectedRole(role)}
                  className={cn(
                    "rounded-xl border-2 px-4 py-3 text-sm font-medium capitalize transition-all",
                    selectedRole === role
                      ? "border-primary bg-primary/5 text-primary shadow-sm"
                      : "border-transparent bg-muted/50 text-foreground hover:bg-muted"
                  )}
                >
                  {role}
                </button>
              ))}
            </div>
            <div className="mt-8 flex justify-end">
              <Button
                onClick={() => setStep("technologies")}
                disabled={!selectedRole}
              >
                Continue
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Step 2: Technologies */}
      {step === "technologies" && (
        <Card>
          <CardHeader>
            <CardTitle>Select Technologies</CardTitle>
            <CardDescription>
              Choose the languages and frameworks you work with
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-8">
            <div>
              <h3 className="mb-3 text-sm font-semibold uppercase tracking-wider text-muted-foreground">
                Languages
              </h3>
              <div className="flex flex-wrap gap-2">
                {options.languages.map((lang) => (
                  <button
                    key={lang}
                    onClick={() =>
                      toggleItem(lang, selectedLanguages, setSelectedLanguages)
                    }
                    className={cn(
                      "rounded-lg border px-3 py-1.5 text-sm font-medium transition-all",
                      selectedLanguages.includes(lang)
                        ? "border-primary bg-primary/10 text-primary"
                        : "border-border bg-background text-foreground hover:border-primary/30 hover:bg-accent/50"
                    )}
                  >
                    {lang}
                  </button>
                ))}
              </div>
            </div>
            <div>
              <h3 className="mb-3 text-sm font-semibold uppercase tracking-wider text-muted-foreground">
                Frameworks
              </h3>
              <div className="flex flex-wrap gap-2">
                {options.frameworks.map((fw) => (
                  <button
                    key={fw}
                    onClick={() =>
                      toggleItem(fw, selectedFrameworks, setSelectedFrameworks)
                    }
                    className={cn(
                      "rounded-lg border px-3 py-1.5 text-sm font-medium transition-all",
                      selectedFrameworks.includes(fw)
                        ? "border-primary bg-primary/10 text-primary"
                        : "border-border bg-background text-foreground hover:border-primary/30 hover:bg-accent/50"
                    )}
                  >
                    {fw}
                  </button>
                ))}
              </div>
            </div>
            <div className="flex justify-between">
              <Button variant="outline" onClick={() => setStep("role")}>
                Back
              </Button>
              <Button
                onClick={() => setStep("confirm")}
                disabled={selectedLanguages.length === 0}
              >
                Continue
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Step 3: Confirm */}
      {step === "confirm" && (
        <Card>
          <CardHeader>
            <CardTitle>Confirm Your Profile</CardTitle>
            <CardDescription>
              Review your selections before we set up your assessment
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-3 rounded-xl bg-muted/50 p-4">
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">Role</span>
                <span className="font-medium capitalize">{selectedRole}</span>
              </div>
              <div className="border-t border-border/50" />
              <div className="flex items-start justify-between gap-4">
                <span className="shrink-0 text-sm text-muted-foreground">
                  Languages
                </span>
                <div className="flex flex-wrap justify-end gap-1.5">
                  {selectedLanguages.map((l) => (
                    <span
                      key={l}
                      className="rounded-md bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary"
                    >
                      {l}
                    </span>
                  ))}
                </div>
              </div>
              <div className="border-t border-border/50" />
              <div className="flex items-start justify-between gap-4">
                <span className="shrink-0 text-sm text-muted-foreground">
                  Frameworks
                </span>
                <div className="flex flex-wrap justify-end gap-1.5">
                  {selectedFrameworks.length > 0 ? (
                    selectedFrameworks.map((f) => (
                      <span
                        key={f}
                        className="rounded-md bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary"
                      >
                        {f}
                      </span>
                    ))
                  ) : (
                    <span className="text-sm text-muted-foreground">
                      None selected
                    </span>
                  )}
                </div>
              </div>
            </div>
            <div className="flex justify-between pt-2">
              <Button
                variant="outline"
                onClick={() => setStep("technologies")}
              >
                Back
              </Button>
              <Button
                onClick={handleSubmit}
                disabled={createProfile.isPending}
              >
                {createProfile.isPending ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" />
                    Saving...
                  </>
                ) : (
                  "Complete Setup"
                )}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
