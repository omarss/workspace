import type { PatternMatch, UiNode } from "../schema/index.js";
import { OtpScreenDetector } from "./detectors/auth.js";
import { CheckoutFormDetector, PaymentPickerDetector } from "./detectors/commerce.js";
import {
  DashboardCardsDetector,
  EmptyStateDetector,
  ErrorStateDetector,
  ListWithActionsDetector,
  SearchSurfaceDetector,
  SettingsPageDetector,
} from "./detectors/content.js";
import { LoginFormDetector, SignupFormDetector } from "./detectors/login-form.js";
import {
  BottomNavigationDetector,
  TabsDetector,
  TopNavigationDetector,
} from "./detectors/navigation.js";
import {
  BottomSheetDetector,
  ModalDialogDetector,
  ToastDetector,
} from "./detectors/overlay.js";
import type { PatternDetector } from "./types.js";

/**
 * Priority order for pattern resolution when multiple patterns overlap.
 * Lower index = higher priority.
 */
const PRIORITY_ORDER = [
  // Blocking overlays first
  "modal_dialog",
  "bottom_sheet",
  "toast",
  // Auth and verification
  "otp_screen",
  "login_form",
  "signup_form",
  // Transactional
  "checkout_form",
  "payment_picker",
  // Navigation
  "top_navigation",
  "bottom_navigation",
  "tabs",
  // Content
  "search_surface",
  "settings_page",
  "dashboard_cards",
  "list_with_actions",
  "error_state",
  "empty_state",
] as const;

/**
 * All registered pattern detectors for the MVP set.
 */
function createDefaultDetectors(): PatternDetector[] {
  return [
    // Auth
    new LoginFormDetector(),
    new SignupFormDetector(),
    new OtpScreenDetector(),
    // Overlays
    new ModalDialogDetector(),
    new BottomSheetDetector(),
    new ToastDetector(),
    // Navigation
    new TopNavigationDetector(),
    new BottomNavigationDetector(),
    new TabsDetector(),
    // Content
    new SearchSurfaceDetector(),
    new SettingsPageDetector(),
    new DashboardCardsDetector(),
    new ListWithActionsDetector(),
    new EmptyStateDetector(),
    new ErrorStateDetector(),
    // Commerce
    new CheckoutFormDetector(),
    new PaymentPickerDetector(),
  ];
}

/**
 * Run all pattern detectors on the given nodes.
 * Returns matches sorted by priority (overlays first, decorations last).
 */
export function detectPatterns(
  nodes: readonly UiNode[],
  detectors?: PatternDetector[],
): PatternMatch[] {
  const activeDetectors = detectors ?? createDefaultDetectors();
  const matches: PatternMatch[] = [];

  for (const detector of activeDetectors) {
    const match = detector.detect(nodes);
    if (match !== null) {
      matches.push(match);
    }
  }

  // Sort by priority order
  const priorityList: readonly string[] = PRIORITY_ORDER;
  matches.sort((a, b) => {
    const aPriority = priorityList.indexOf(a.kind);
    const bPriority = priorityList.indexOf(b.kind);
    const aIdx = aPriority === -1 ? priorityList.length : aPriority;
    const bIdx = bPriority === -1 ? priorityList.length : bPriority;
    return aIdx - bIdx;
  });

  return matches;
}
