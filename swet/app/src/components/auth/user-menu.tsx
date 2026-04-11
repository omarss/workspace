"use client";

import { useEffect } from "react";
import { signIn, signOut, useSession } from "next-auth/react";
import { LogIn, LogOut, User as UserIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAnonymousStore } from "@/lib/stores/anonymous-store";

export function UserMenu() {
  const { data: session } = useSession();
  const anonToken = useAnonymousStore((s) => s.token);
  const hydrate = useAnonymousStore((s) => s.hydrate);

  useEffect(() => {
    hydrate();
  }, [hydrate]);

  if (anonToken && !session?.user) {
    return (
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <UserIcon className="h-4 w-4" />
          <span>Anonymous</span>
        </div>
        <Button variant="ghost" size="sm" onClick={() => signIn("github")}>
          <LogIn className="h-4 w-4" />
          Sign in
        </Button>
      </div>
    );
  }

  if (!session?.user) return null;

  return (
    <div className="flex items-center gap-3">
      <span className="text-sm font-medium text-foreground/80">
        {session.user.name || session.user.email}
      </span>
      <Button variant="ghost" size="sm" onClick={() => signOut()}>
        <LogOut className="h-4 w-4" />
      </Button>
    </div>
  );
}
