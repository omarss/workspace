import { describe, expect, it } from 'bun:test';
import { interpretConfirmation } from '../src/engage/providers/confirmation-interpreter';
import { ConfirmationResult } from '../src/engage/types';

describe('interpretConfirmation', () => {
  it('matches default tokens', () => {
    expect(interpretConfirmation('yes')).toBe(ConfirmationResult.CONFIRMED);
    expect(interpretConfirmation('2')).toBe(ConfirmationResult.REJECTED);
  });

  it('matches custom tokens', () => {
    const tokens = {
      confirm: ['approve'],
      reject: ['deny'],
    };

    expect(interpretConfirmation('approve', tokens)).toBe(
      ConfirmationResult.CONFIRMED,
    );
    expect(interpretConfirmation('deny', tokens)).toBe(
      ConfirmationResult.REJECTED,
    );
  });
});
