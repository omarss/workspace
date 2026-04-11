import type { UiNode } from "../../schema/index.js";
import {
  buildMatch,
  findMatching,
  isButtonNode,
  isInputNode,
  textMatches,
} from "../types.js";
import type { PatternDetector } from "../types.js";

const IDENTIFIER_PATTERNS = [
  "email",
  "username",
  "user name",
  "phone",
  "account",
  "login",
  "user id",
];
const SECRET_PATTERNS = ["password", "passcode", "pin"];
const SUBMIT_PATTERNS = ["sign in", "log in", "login", "signin", "continue", "submit"];
const SECONDARY_PATTERNS = ["forgot", "create account", "sign up", "register", "reset"];

/**
 * Detects login/sign-in forms.
 *
 * Evidence:
 * - At least one identifier field (email, username, phone)
 * - At least one secret field (password) unless OTP pattern
 * - One primary submit action
 * - Optional secondary actions (forgot password, create account)
 */
export class LoginFormDetector implements PatternDetector {
  readonly kind = "login_form" as const;

  detect(nodes: readonly UiNode[]): ReturnType<PatternDetector["detect"]> {
    const identifierFields = findMatching(nodes, (n) =>
      isInputNode(n) && textMatches(n, IDENTIFIER_PATTERNS),
    );

    const secretFields = findMatching(nodes, (n) =>
      isInputNode(n) && textMatches(n, SECRET_PATTERNS),
    );

    const submitButtons = findMatching(nodes, (n) =>
      isButtonNode(n) && textMatches(n, SUBMIT_PATTERNS),
    );

    const secondaryActions = findMatching(nodes, (n) =>
      textMatches(n, SECONDARY_PATTERNS),
    );

    // Must have at least one identifier field
    if (identifierFields.length === 0) return null;

    // Must have either a secret field or a submit button
    if (secretFields.length === 0 && submitButtons.length === 0) return null;

    // Score calculation
    let confidence = 0.5;

    // Identifier field found
    confidence += 0.15;

    // Secret field found
    if (secretFields.length > 0) confidence += 0.15;

    // Submit button found
    if (submitButtons.length > 0) confidence += 0.1;

    // Secondary actions add minor confidence
    if (secondaryActions.length > 0) confidence += 0.05;

    // Both identifier + secret is strong signal
    if (identifierFields.length > 0 && secretFields.length > 0) {
      confidence += 0.05;
    }

    const allFieldIds = [
      ...identifierFields.map((n) => n.id),
      ...secretFields.map((n) => n.id),
    ];
    const allActionIds = submitButtons.map((n) => n.id);
    const allTexts = [
      ...submitButtons.map((n) => n.text),
      ...secondaryActions.map((n) => n.text),
    ].filter((t) => t.length > 0);

    return buildMatch(
      this.kind,
      Math.min(confidence, 1.0),
      {
        fields: allFieldIds,
        actions: allActionIds,
        texts: allTexts,
      },
      1,
    );
  }
}

/**
 * Detects signup/registration forms.
 */
export class SignupFormDetector implements PatternDetector {
  readonly kind = "signup_form" as const;

  detect(nodes: readonly UiNode[]): ReturnType<PatternDetector["detect"]> {
    const signupPatterns = ["sign up", "signup", "register", "create account", "get started", "join"];
    const confirmPatterns = ["confirm password", "repeat password", "re-enter"];

    const signupActions = findMatching(nodes, (n) =>
      isButtonNode(n) && textMatches(n, signupPatterns),
    );

    const confirmFields = findMatching(nodes, (n) =>
      isInputNode(n) && textMatches(n, confirmPatterns),
    );

    const identifierFields = findMatching(nodes, (n) =>
      isInputNode(n) && textMatches(n, IDENTIFIER_PATTERNS),
    );

    // Need some signup signal
    if (signupActions.length === 0 && confirmFields.length === 0) return null;
    if (identifierFields.length === 0) return null;

    let confidence = 0.5;
    if (signupActions.length > 0) confidence += 0.2;
    if (confirmFields.length > 0) confidence += 0.15;
    if (identifierFields.length > 1) confidence += 0.1;

    return buildMatch(
      this.kind,
      Math.min(confidence, 1.0),
      {
        fields: [
          ...identifierFields.map((n) => n.id),
          ...confirmFields.map((n) => n.id),
        ],
        actions: signupActions.map((n) => n.id),
        texts: signupActions.map((n) => n.text).filter((t) => t.length > 0),
      },
      1,
    );
  }
}
