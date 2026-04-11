"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { apiClient } from "@/lib/api/client";
import { useAnonymousStore } from "@/lib/stores/anonymous-store";
import type { User } from "@/lib/types";

interface AnonymousSessionResponse {
  token: string;
  user: User;
}

export function TryAnonymousButton() {
  const [isLoading, setIsLoading] = useState(false);
  const setSession = useAnonymousStore((s) => s.setSession);
  const router = useRouter();

  const handleClick = async () => {
    setIsLoading(true);
    try {
      const data = await apiClient<AnonymousSessionResponse>(
        "/api/v1/auth/anonymous",
        { method: "POST", noAuth: true }
      );
      setSession(data.token, data.user.id);
      router.push("/onboarding");
    } catch {
      setIsLoading(false);
    }
  };

  return (
    <Button
      variant="outline"
      size="lg"
      onClick={handleClick}
      disabled={isLoading}
    >
      {isLoading ? (
        <>
          <Loader2 className="h-4 w-4 animate-spin" />
          Setting up...
        </>
      ) : (
        "Try without signing in"
      )}
    </Button>
  );
}
