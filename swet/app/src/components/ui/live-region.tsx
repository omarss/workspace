"use client";

import { useEffect, useRef, useState } from "react";

interface LiveRegionProps {
  /** The message to announce to screen readers. Change this to trigger announcements. */
  message: string;
  /** Politeness level: "polite" waits for idle, "assertive" interrupts immediately. */
  politeness?: "polite" | "assertive";
}

/**
 * Accessible live region that announces messages to screen readers.
 * Visually hidden but accessible to assistive technology.
 *
 * Usage:
 *   <LiveRegion message={`${answered} of ${total} questions answered`} />
 */
export function LiveRegion({
  message,
  politeness = "polite",
}: LiveRegionProps) {
  // Toggle between two containers to force screen reader re-announcement
  const [current, setCurrent] = useState(0);
  const prevMessage = useRef(message);

  useEffect(() => {
    if (message !== prevMessage.current) {
      setCurrent((c) => (c === 0 ? 1 : 0));
      prevMessage.current = message;
    }
  }, [message]);

  return (
    <div className="sr-only">
      <div aria-live={politeness} aria-atomic="true">
        {current === 0 ? message : ""}
      </div>
      <div aria-live={politeness} aria-atomic="true">
        {current === 1 ? message : ""}
      </div>
    </div>
  );
}
