import { ConfirmationResult } from '../types';

export interface ConfirmationTokens {
  confirm?: string[];
  reject?: string[];
}

const DEFAULT_CONFIRM_VALUES = ['1', 'y', 'yes', 'confirm', 'confirmed', 'ok'];
const DEFAULT_REJECT_VALUES = ['2', 'n', 'no', 'reject', 'rejected', 'cancel'];
const DEFAULT_CONFIRM_SET = new Set(DEFAULT_CONFIRM_VALUES);
const DEFAULT_REJECT_SET = new Set(DEFAULT_REJECT_VALUES);

export function interpretConfirmation(
  value: string | null | undefined,
  tokens?: ConfirmationTokens,
): ConfirmationResult | null {
  if (!value) {
    return null;
  }

  const normalized = normalizeToken(value);
  if (!normalized) {
    return null;
  }

  const confirmTokens = buildTokenSet(DEFAULT_CONFIRM_SET, tokens?.confirm);
  const rejectTokens = buildTokenSet(DEFAULT_REJECT_SET, tokens?.reject);

  if (confirmTokens.has(normalized)) {
    return ConfirmationResult.CONFIRMED;
  }

  if (rejectTokens.has(normalized)) {
    return ConfirmationResult.REJECTED;
  }

  return null;
}

function normalizeToken(value: string): string {
  return value.trim().toLowerCase();
}

function buildTokenSet(defaults: Set<string>, extras?: string[]): Set<string> {
  if (!extras || extras.length === 0) {
    return defaults;
  }

  const combined = new Set(defaults);
  for (const entry of extras) {
    const normalized = normalizeToken(entry);
    if (normalized) {
      combined.add(normalized);
    }
  }
  return combined;
}
