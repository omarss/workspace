import { randomUUID } from 'node:crypto';
import { GoneException, Inject, Injectable, NotFoundException } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import type { CreateConfirmationRequestDto } from './dto/create-confirmation-request.dto';
import { ENGAGE_STORE, type EngageStore } from './engage.store';
import { CallbackService } from './providers/callback.service';
import { ConfirmationResult, type ConfirmationRequest } from './types';

@Injectable()
export class EngageService {
  private readonly defaultTtlSeconds: number;

  constructor(
    @Inject(ENGAGE_STORE) private readonly store: EngageStore,
    private readonly configService: ConfigService,
    private readonly callbackService: CallbackService,
  ) {
    const configuredTtl = this.configService.get<string>(
      'CONFIRMATION_TTL_SECONDS',
    );
    const parsed = configuredTtl ? Number(configuredTtl) : NaN;
    this.defaultTtlSeconds =
      Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
  }

  async create(dto: CreateConfirmationRequestDto): Promise<ConfirmationRequest> {
    const now = new Date();
    const nowIso = now.toISOString();

    const ttlSeconds = dto.ttlSeconds ?? this.defaultTtlSeconds;
    const expiresAt =
      ttlSeconds > 0
        ? new Date(now.getTime() + ttlSeconds * 1000).toISOString()
        : undefined;

    const req: ConfirmationRequest = {
      id: randomUUID(),
      mobileNumber: dto.mobileNumber,
      message: dto.message,
      language: dto.language,
      channel: dto.channel,
      result: ConfirmationResult.NOT_CONFIRMED,
      callbackUrl: dto.callbackUrl,
      expiresAt,
      createdAt: nowIso,
      updatedAt: nowIso,
    };

    await this.store.create(req);
    return req;
  }

  async get(requestId: string): Promise<ConfirmationRequest> {
    const existing = await this.store.get(requestId);
    if (!existing) {
      throw new NotFoundException('Request not found');
    }

    if (this.isExpired(existing)) {
      throw new GoneException('Confirmation request has expired');
    }

    return existing;
  }

  private isExpired(request: ConfirmationRequest): boolean {
    if (!request.expiresAt) {
      return false;
    }

    if (request.result !== ConfirmationResult.NOT_CONFIRMED) {
      return false;
    }

    return new Date(request.expiresAt) < new Date();
  }

  async getByProviderMessageId(
    providerMessageId: string,
  ): Promise<ConfirmationRequest | null> {
    return this.store.getByProviderMessageId(providerMessageId);
  }

  async setResult(
    requestId: string,
    result: ConfirmationResult,
  ): Promise<ConfirmationRequest> {
    const existing = await this.store.get(requestId);
    if (!existing) {
      throw new NotFoundException('Request not found');
    }

    if (this.isExpired(existing)) {
      throw new GoneException('Confirmation request has expired');
    }

    const updatedAt = new Date().toISOString();
    const updated = await this.store.setResult(requestId, result, updatedAt);
    if (!updated) {
      throw new NotFoundException('Request not found');
    }

    void this.callbackService.notify(updated);

    return updated;
  }

  async setProviderInfo(
    requestId: string,
    provider: string,
    providerMessageId: string,
  ): Promise<ConfirmationRequest> {
    const updatedAt = new Date().toISOString();
    const updated = await this.store.setProviderInfo(
      requestId,
      provider,
      providerMessageId,
      updatedAt,
    );
    if (!updated) {
      throw new NotFoundException('Request not found');
    }
    return updated;
  }
}
