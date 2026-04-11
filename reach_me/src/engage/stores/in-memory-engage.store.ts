import { Injectable } from '@nestjs/common';
import type { EngageStore } from '../engage.store';
import type { ConfirmationRequest, ConfirmationResult } from '../types';

@Injectable()
export class InMemoryEngageStore implements EngageStore {
  private readonly store = new Map<string, ConfirmationRequest>();
  private readonly providerIndex = new Map<string, string>();

  create(request: ConfirmationRequest): Promise<ConfirmationRequest> {
    this.store.set(request.id, request);
    if (request.providerMessageId) {
      this.providerIndex.set(request.providerMessageId, request.id);
    }
    return Promise.resolve(request);
  }

  get(requestId: string): Promise<ConfirmationRequest | null> {
    return Promise.resolve(this.store.get(requestId) ?? null);
  }

  getByProviderMessageId(
    providerMessageId: string,
  ): Promise<ConfirmationRequest | null> {
    const requestId = this.providerIndex.get(providerMessageId);
    if (!requestId) {
      return Promise.resolve(null);
    }
    return this.get(requestId);
  }

  setResult(
    requestId: string,
    result: ConfirmationResult,
    updatedAt: string,
  ): Promise<ConfirmationRequest | null> {
    const existing = this.store.get(requestId);
    if (!existing) {
      return Promise.resolve(null);
    }

    const updated: ConfirmationRequest = {
      ...existing,
      result,
      updatedAt,
    };
    this.store.set(requestId, updated);
    return Promise.resolve(updated);
  }

  setProviderInfo(
    requestId: string,
    provider: string,
    providerMessageId: string,
    updatedAt: string,
  ): Promise<ConfirmationRequest | null> {
    const existing = this.store.get(requestId);
    if (!existing) {
      return Promise.resolve(null);
    }

    if (existing.providerMessageId) {
      this.providerIndex.delete(existing.providerMessageId);
    }
    this.providerIndex.set(providerMessageId, requestId);

    const updated: ConfirmationRequest = {
      ...existing,
      provider,
      providerMessageId,
      updatedAt,
    };
    this.store.set(requestId, updated);
    return Promise.resolve(updated);
  }
}
