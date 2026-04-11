"use client";

import { useCallback, useSyncExternalStore } from "react";

/**
 * Track browser online/offline state using navigator.onLine.
 * Returns true when online, false when offline.
 */
export function useOnlineStatus(): boolean {
  const subscribe = useCallback((callback: () => void) => {
    window.addEventListener("online", callback);
    window.addEventListener("offline", callback);
    return () => {
      window.removeEventListener("online", callback);
      window.removeEventListener("offline", callback);
    };
  }, []);

  const getSnapshot = useCallback(() => navigator.onLine, []);

  // SSR fallback: assume online
  const getServerSnapshot = useCallback(() => true, []);

  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}
