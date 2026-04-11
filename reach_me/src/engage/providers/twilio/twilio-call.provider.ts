import { Injectable } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import type { ChannelProvider, ProviderSendResult } from '../provider.types';
import { Channel, type ConfirmationRequest } from '../../types';

@Injectable()
export class TwilioCallProvider implements ChannelProvider {
  name = 'twilio_call';

  constructor(private readonly configService: ConfigService) {}

  supports(channel: Channel): boolean {
    return channel === Channel.CALL;
  }

  isConfigured(): boolean {
    return Boolean(
      this.configService.get<string>('TWILIO_ACCOUNT_SID') &&
        this.configService.get<string>('TWILIO_AUTH_TOKEN') &&
        this.configService.get<string>('TWILIO_CALL_FROM') &&
        this.configService.get<string>('PUBLIC_BASE_URL'),
    );
  }

  async send(
    request: ConfirmationRequest,
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    _message: string,
  ): Promise<ProviderSendResult> {
    if (!this.isConfigured()) {
      return { provider: this.name, status: 'skipped' };
    }

    const accountSid = this.configService.get<string>('TWILIO_ACCOUNT_SID');
    const authToken = this.configService.get<string>('TWILIO_AUTH_TOKEN');
    const from = this.configService.get<string>('TWILIO_CALL_FROM');
    const baseUrl = this.configService.get<string>('PUBLIC_BASE_URL');

    if (!accountSid || !authToken || !from || !baseUrl) {
      return { provider: this.name, status: 'skipped' };
    }

    const url = new URL('/webhooks/twilio/voice', baseUrl);
    url.searchParams.set('requestId', request.id);

    const params = new URLSearchParams({
      To: request.mobileNumber,
      From: from,
      Url: url.toString(),
      Method: 'POST',
    });

    const response = await this.fetchWithTimeout(
      `https://api.twilio.com/2010-04-01/Accounts/${accountSid}/Calls.json`,
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
        `Twilio call error ${response.status}: ${text.slice(0, 200)}`,
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
