import type { ConfirmationRequest, ConfirmationResult } from './types';

export const ENGAGE_STORE = Symbol('ENGAGE_STORE');

export interface EngageStore {
  create(request: ConfirmationRequest): Promise<ConfirmationRequest>;
  get(requestId: string): Promise<ConfirmationRequest | null>;
  getByProviderMessageId(
    providerMessageId: string,
  ): Promise<ConfirmationRequest | null>;
  setResult(
    requestId: string,
    result: ConfirmationResult,
    updatedAt: string,
  ): Promise<ConfirmationRequest | null>;
  setProviderInfo(
    requestId: string,
    provider: string,
    providerMessageId: string,
    updatedAt: string,
  ): Promise<ConfirmationRequest | null>;
}
