/**
 * Lightweight analytics event system.
 *
 * Logs key funnel events. In dev, events go to console.
 * Replace the `send` function with a real provider (PostHog, Amplitude, etc.) in production.
 */

type EventName =
  | "app_opened"
  | "guest_start"
  | "recording_started"
  | "recording_stopped"
  | "recognition_success"
  | "recognition_fail"
  | "first_recitation"
  | "account_created"
  | "login"
  | "guest_limit_reached";

type EventProperties = Record<string, string | number | boolean | null>;

function send(event: EventName, properties?: EventProperties): void {
  if (__DEV__) {
    console.log(`[analytics] ${event}`, properties ?? "");
  }
  // TODO: Replace with real provider
  // e.g. posthog.capture(event, properties);
}

export const analytics = {
  track: send,

  /** First app open as guest (no stored token) */
  guestStart: () => send("guest_start"),

  /** User started a recording */
  recordingStarted: () => send("recording_started"),

  /** User stopped a recording */
  recordingStopped: () => send("recording_stopped"),

  /** Recognition returned a match */
  recognitionSuccess: (surah: number, ayah: number, score: number) =>
    send("recognition_success", { surah, ayah, score }),

  /** Recognition returned no match */
  recognitionFail: () => send("recognition_fail"),

  /** User's very first successful recitation */
  firstRecitation: () => send("first_recitation"),

  /** User created an account (upgraded from guest) */
  accountCreated: () => send("account_created"),

  /** User logged in */
  login: () => send("login"),

  /** Guest hit daily limit */
  guestLimitReached: () => send("guest_limit_reached"),
};
