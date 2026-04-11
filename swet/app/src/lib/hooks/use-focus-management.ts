"use client";

import { useEffect, useRef } from "react";

/**
 * Focus an element on mount. Useful for setting initial focus
 * when navigating between questions or opening dialogs.
 */
export function useFocusOnMount<T extends HTMLElement>() {
  const ref = useRef<T>(null);

  useEffect(() => {
    // Small delay to let the DOM settle after render
    const timer = setTimeout(() => {
      ref.current?.focus();
    }, 0);
    return () => clearTimeout(timer);
  }, []);

  return ref;
}

/**
 * Trap focus within a container element. Used for modal dialogs
 * and other overlay components that should contain keyboard navigation.
 */
export function useFocusTrap<T extends HTMLElement>() {
  const containerRef = useRef<T>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    function handleKeyDown(e: KeyboardEvent) {
      if (e.key !== "Tab" || !container) return;

      const focusable = container.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'
      );

      if (focusable.length === 0) return;

      const first = focusable[0];
      const last = focusable[focusable.length - 1];

      if (e.shiftKey) {
        if (document.activeElement === first) {
          e.preventDefault();
          last.focus();
        }
      } else {
        if (document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    }

    container.addEventListener("keydown", handleKeyDown);
    return () => container.removeEventListener("keydown", handleKeyDown);
  }, []);

  return containerRef;
}
