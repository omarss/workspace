import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import type { ConfirmationRequest } from '../types';

export interface CallbackPayload {
  requestId: string;
  mobileNumber: string;
  channel: string;
  result: string;
  provider?: string;
  updatedAt: string;
}

@Injectable()
export class CallbackService {
  private readonly logger = new Logger(CallbackService.name);
  private readonly timeoutMs: number;

  constructor(private readonly configService: ConfigService) {
    const configured = this.configService.get<string>('CALLBACK_TIMEOUT_MS');
    const parsed = configured ? Number(configured) : NaN;
    this.timeoutMs = Number.isFinite(parsed) && parsed > 0 ? parsed : 10000;
  }

  async notify(request: ConfirmationRequest): Promise<void> {
    if (!request.callbackUrl) {
      return;
    }

    const payload: CallbackPayload = {
      requestId: request.id,
      mobileNumber: request.mobileNumber,
      channel: request.channel,
      result: request.result,
      provider: request.provider,
      updatedAt: request.updatedAt,
    };

    try {
      const response = await this.fetchWithTimeout(request.callbackUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        const text = await response.text();
        this.logger.warn(
          `Callback failed for ${request.id}: ${response.status} - ${text.slice(0, 200)}`,
        );
      }
    } catch (error) {
      this.logger.warn(
        `Callback error for ${request.id}: ${(error as Error).message}`,
      );
    }
  }

  private async fetchWithTimeout(
    url: string,
    options: RequestInit,
  ): Promise<Response> {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), this.timeoutMs);

    try {
      return await fetch(url, { ...options, signal: controller.signal });
    } finally {
      clearTimeout(timeout);
    }
  }
}
