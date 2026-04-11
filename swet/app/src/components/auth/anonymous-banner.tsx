"use client";

import { useEffect, useState } from "react";
import { signIn } from "next-auth/react";
import { AlertTriangle } from "lucide-react";
import { useAnonymousStore } from "@/lib/stores/anonymous-store";

export function AnonymousBanner() {
  const [hydrated, setHydrated] = useState(false);
  const token = useAnonymousStore((s) => s.token);
  const hydrate = useAnonymousStore((s) => s.hydrate);

  useEffect(() => {
    hydrate();
    setHydrated(true);
  }, [hydrate]);

  if (!hydrated || !token) return null;

  return (
    <div className="flex items-center justify-center gap-2 border-b border-warning/30 bg-warning/10 px-4 py-2.5 text-sm text-warning dark:text-warning">
      <AlertTriangle className="h-4 w-4 shrink-0" />
      <span>
        Anonymous mode &mdash; progress will not be saved after closing this tab.{" "}
        <button
          onClick={() => signIn("github")}
          className="font-semibold underline underline-offset-2 transition-colors hover:text-foreground"
        >
          Sign in with GitHub
        </button>
      </span>
    </div>
  );
}
