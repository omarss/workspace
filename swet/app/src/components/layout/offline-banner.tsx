"use client";

import { WifiOff } from "lucide-react";
import { useOnlineStatus } from "@/lib/hooks/use-online-status";

export function OfflineBanner() {
  const isOnline = useOnlineStatus();

  if (isOnline) return null;

  return (
    <div
      role="alert"
      className="flex items-center justify-center gap-2 bg-amber-600 px-4 py-2 text-center text-sm font-medium text-white"
    >
      <WifiOff className="h-4 w-4" />
      You are offline. Changes will be saved locally and synced when you
      reconnect.
    </div>
  );
}
