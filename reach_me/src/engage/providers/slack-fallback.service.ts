import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import type { ConfirmationRequest } from '../types';

@Injectable()
export class SlackFallbackService {
  private readonly logger = new Logger(SlackFallbackService.name);

  constructor(private readonly configService: ConfigService) {}

  async notifyDispatchFailure(
    request: ConfirmationRequest,
    providerName: string,
    error: Error,
  ): Promise<void> {
    const webhookUrl = this.configService.get<string>('SLACK_WEBHOOK_URL');
    if (!webhookUrl) {
      return;
    }

    const includeMessage =
      this.configService.get<string>('SLACK_FALLBACK_INCLUDE_MESSAGE') ===
      'true';

    const lines = [
      `Dispatch failure for request ${request.id}`,
      `Provider: ${providerName}`,
      `Channel: ${request.channel}`,
      `Mobile: ${request.mobileNumber}`,
      `Language: ${request.language}`,
      `Error: ${error.message}`,
    ];

    if (includeMessage) {
      lines.push(`Message: ${request.message}`);
    }

    try {
      const response = await this.fetchWithTimeout(webhookUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ text: lines.join('\n') }),
      });

      if (!response.ok) {
        const text = await response.text();
        this.logger.warn(
          `Slack webhook response ${response.status}: ${text.slice(0, 200)}`,
        );
      }
    } catch (error) {
      this.logger.warn(
        `Slack webhook failed: ${(error as Error).message}`,
      );
    }
  }

  private async fetchWithTimeout(
    url: string,
    options: RequestInit,
    timeoutMs = 10000,
  ): Promise<Response> {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);

    try {
      return await fetch(url, { ...options, signal: controller.signal });
    } finally {
      clearTimeout(timeout);
    }
  }
}
