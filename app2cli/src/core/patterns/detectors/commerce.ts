import type { UiNode } from "../../schema/index.js";
import { buildMatch, findMatching, isInputNode, textMatches } from "../types.js";
import type { PatternDetector } from "../types.js";

/**
 * Detects checkout forms.
 */
export class CheckoutFormDetector implements PatternDetector {
  readonly kind = "checkout_form" as const;

  detect(nodes: readonly UiNode[]): ReturnType<PatternDetector["detect"]> {
    const checkoutPatterns = [
      "checkout",
      "place order",
      "complete purchase",
      "pay now",
      "buy now",
      "order summary",
      "shipping",
      "billing",
    ];

    const checkoutElements = findMatching(nodes, (n) =>
      textMatches(n, checkoutPatterns) && n.visible,
    );

    if (checkoutElements.length === 0) return null;

    const formFields = findMatching(nodes, (n) => isInputNode(n) && n.visible);
    const payButtons = findMatching(
      nodes,
      (n) =>
        n.clickable &&
        textMatches(n, ["pay", "place order", "checkout", "buy", "purchase"]),
    );

    let confidence = 0.65;
    if (formFields.length >= 3) confidence += 0.1;
    if (payButtons.length > 0) confidence += 0.15;
    if (checkoutElements.length >= 2) confidence += 0.05;

    return buildMatch(
      this.kind,
      Math.min(confidence, 1.0),
      {
        fields: formFields.map((n) => n.id),
        actions: payButtons.map((n) => n.id),
        texts: checkoutElements.map((n) => n.text).filter((t) => t.length > 0),
      },
      1,
    );
  }
}

/**
 * Detects payment method picker screens.
 */
export class PaymentPickerDetector implements PatternDetector {
  readonly kind = "payment_picker" as const;

  detect(nodes: readonly UiNode[]): ReturnType<PatternDetector["detect"]> {
    const paymentPatterns = [
      "payment method",
      "pay with",
      "credit card",
      "debit card",
      "visa",
      "mastercard",
      "paypal",
      "apple pay",
      "google pay",
      "add card",
    ];

    const paymentNodes = findMatching(nodes, (n) =>
      textMatches(n, paymentPatterns) && n.visible,
    );

    if (paymentNodes.length < 2) return null;

    let confidence = 0.7;
    if (paymentNodes.length >= 3) confidence += 0.1;

    const selectablePayments = paymentNodes.filter((n) => n.clickable);
    if (selectablePayments.length >= 2) confidence += 0.1;

    return buildMatch(
      this.kind,
      Math.min(confidence, 1.0),
      {
        items: paymentNodes.map((n) => n.id),
        texts: paymentNodes.map((n) => n.text).filter((t) => t.length > 0),
      },
      1,
    );
  }
}
