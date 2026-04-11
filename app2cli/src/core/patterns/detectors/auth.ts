import type { UiNode } from "../../schema/index.js";
import { buildMatch, findMatching, isInputNode, textMatches } from "../types.js";
import type { PatternDetector } from "../types.js";

/**
 * Detects OTP/verification code entry screens.
 */
export class OtpScreenDetector implements PatternDetector {
  readonly kind = "otp_screen" as const;

  detect(nodes: readonly UiNode[]): ReturnType<PatternDetector["detect"]> {
    const otpPatterns = [
      "verification code",
      "otp",
      "enter code",
      "one-time",
      "verify",
      "confirmation code",
      "6-digit",
      "4-digit",
    ];

    const otpLabels = findMatching(nodes, (n) =>
      textMatches(n, otpPatterns) && n.visible,
    );

    const inputFields = findMatching(nodes, (n) => isInputNode(n) && n.visible);

    if (otpLabels.length === 0) return null;

    let confidence = 0.7;

    // Multiple small input fields suggest individual digit entry
    if (inputFields.length >= 4 && inputFields.length <= 8) {
      confidence += 0.15;
    } else if (inputFields.length >= 1) {
      confidence += 0.05;
    }

    // Strong OTP text signal
    if (otpLabels.length >= 2) confidence += 0.05;

    return buildMatch(
      this.kind,
      Math.min(confidence, 1.0),
      {
        fields: inputFields.map((n) => n.id),
        items: otpLabels.map((n) => n.id),
        texts: otpLabels.map((n) => n.text).filter((t) => t.length > 0),
      },
      1,
    );
  }
}
