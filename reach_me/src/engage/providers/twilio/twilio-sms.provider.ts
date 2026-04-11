import { Injectable } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import type { ChannelProvider, ProviderSendResult } from '../provider.types';
import { Channel, type ConfirmationRequest } from '../../types';

@Injectable()
export class TwilioSmsProvider implements ChannelProvider {
  name = 'twilio_sms';

  constructor(private readonly configService: ConfigService) {}

  supports(channel: Channel): boolean {
    return channel === Channel.SMS;
  }

  isConfigured(): boolean {
    return Boolean(
      this.configService.get<string>('TWILIO_ACCOUNT_SID') &&
        this.configService.get<string>('TWILIO_AUTH_TOKEN') &&
        this.configService.get<string>('TWILIO_SMS_FROM'),
    );
  }

  async send(
    request: ConfirmationRequest,
    message: string,
  ): Promise<ProviderSendResult> {
    if (!this.isConfigured()) {
      return { provider: this.name, status: 'skipped' };
    }

    const accountSid = this.configService.get<string>('TWILIO_ACCOUNT_SID');
    const authToken = this.configService.get<string>('TWILIO_AUTH_TOKEN');
    const from = this.configService.get<string>('TWILIO_SMS_FROM');
    const baseUrl = this.configService.get<string>('PUBLIC_BASE_URL');
    const overrideCallback = this.configService.get<string>(
      'TWILIO_SMS_STATUS_CALLBACK_URL',
    );

    if (!accountSid || !authToken || !from) {
      return { provider: this.name, status: 'skipped' };
    }

    const callbackUrl =
      overrideCallback ?? this.buildCallbackUrl(baseUrl, request.id);

    const params = new URLSearchParams({
      To: request.mobileNumber,
      From: from,
      Body: message,
    });

    if (callbackUrl) {
      params.set('StatusCallback', callbackUrl);
    }

    const response = await this.fetchWithTimeout(
      `https://api.twilio.com/2010-04-01/Accounts/${accountSid}/Messages.json`,
      {
        method: 'POST',
        headers: {
          Authorization: this.buildAuthHeader(accountSid, authToken),
          'Content-Type': 'application/x-www-form-urlencoded',
        },
        body: params.toString(),
      },
    );

    if (!response.ok) {
      const text = await response.text();
      throw new Error(
        `Twilio SMS error ${response.status}: ${text.slice(0, 200)}`,
      );
    }

    const data = (await response.json()) as { sid?: string };
    return {
      provider: this.name,
      providerMessageId: data.sid,
      status: 'sent',
    };
  }

  private buildAuthHeader(accountSid: string, authToken: string): string {
    const token = Buffer.from(`${accountSid}:${authToken}`).toString('base64');
    return `Basic ${token}`;
  }

  private buildCallbackUrl(baseUrl: string | undefined, requestId: string) {
    if (!baseUrl) {
      return undefined;
    }

    const url = new URL('/webhooks/twilio/sms/status', baseUrl);
    url.searchParams.set('requestId', requestId);
    return url.toString();
  }

  private async fetchWithTimeout(
    url: string,
    options: RequestInit,
    timeoutMs = 30000,
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
