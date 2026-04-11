import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Channel } from '../types';
import type { ConfirmationRequest } from '../types';
import { EngageService } from '../engage.service';
import { MessageComposerService } from './message-composer.service';
import { SlackFallbackService } from './slack-fallback.service';
import { MetaWhatsAppProvider } from './whatsapp/meta-whatsapp.service';
import { TwilioCallProvider } from './twilio/twilio-call.provider';
import { TwilioSmsProvider } from './twilio/twilio-sms.provider';
import { TwilioWhatsAppProvider } from './twilio/twilio-whatsapp.provider';

@Injectable()
export class EngageDispatchService {
  private readonly logger = new Logger(EngageDispatchService.name);

  constructor(
    private readonly configService: ConfigService,
    private readonly engageService: EngageService,
    private readonly messageComposer: MessageComposerService,
    private readonly metaWhatsAppProvider: MetaWhatsAppProvider,
    private readonly twilioWhatsAppProvider: TwilioWhatsAppProvider,
    private readonly twilioCallProvider: TwilioCallProvider,
    private readonly twilioSmsProvider: TwilioSmsProvider,
    private readonly slackFallback: SlackFallbackService,
  ) {}

  async dispatch(
    request: ConfirmationRequest,
    options?: { throwOnFailure?: boolean },
  ): Promise<void> {
    const throwOnFailure = options?.throwOnFailure ?? false;
    const provider = this.resolveProvider(request.channel);
    if (!provider) {
      await this.slackFallback.notifyDispatchFailure(
        request,
        'none',
        new Error('No provider configured'),
      );
      return;
    }

    const message =
      request.channel === Channel.CALL
        ? request.message
        : await this.messageComposer.compose(request, request.channel);

    try {
      const result = await provider.send(request, message);
      if (result.status === 'skipped') {
        await this.slackFallback.notifyDispatchFailure(
          request,
          result.provider,
          new Error('Provider not configured'),
        );
        return;
      }

      if (result.providerMessageId) {
        await this.engageService.setProviderInfo(
          request.id,
          result.provider,
          result.providerMessageId,
        );
      }
    } catch (error) {
      const err = error as Error;
      this.logger.warn(
        `Dispatch failed for ${request.id} via ${provider.name}: ${err.message}`,
      );
      await this.slackFallback.notifyDispatchFailure(
        request,
        provider.name,
        err,
      );
      if (throwOnFailure) {
        throw err;
      }
    }
  }

  private resolveProvider(channel: Channel) {
    if (channel === Channel.WHATSAPP_TEXT || channel === Channel.WHATSAPP_VOICE) {
      const configured = this.configService
        .get<string>('WHATSAPP_PROVIDER')
        ?.toLowerCase();
      if (configured === 'twilio') {
        if (!this.twilioWhatsAppProvider.supports(channel)) {
          this.logger.warn(
            `WHATSAPP_PROVIDER=twilio does not support channel ${channel}`,
          );
          return null;
        }
        return this.twilioWhatsAppProvider;
      }

      if (configured === 'meta') {
        if (!this.metaWhatsAppProvider.supports(channel)) {
          this.logger.warn(
            `WHATSAPP_PROVIDER=meta does not support channel ${channel}`,
          );
          return null;
        }
        return this.metaWhatsAppProvider;
      }

      if (
        this.metaWhatsAppProvider.isConfigured() &&
        this.metaWhatsAppProvider.supports(channel)
      ) {
        return this.metaWhatsAppProvider;
      }

      if (
        this.twilioWhatsAppProvider.isConfigured() &&
        this.twilioWhatsAppProvider.supports(channel)
      ) {
        return this.twilioWhatsAppProvider;
      }

      return null;
    }

    if (channel === Channel.CALL) {
      const configured = this.configService
        .get<string>('CALL_PROVIDER')
        ?.toLowerCase();
      if (configured === 'twilio') {
        if (!this.twilioCallProvider.supports(channel)) {
          this.logger.warn(
            `CALL_PROVIDER=twilio does not support channel ${channel}`,
          );
          return null;
        }
        return this.twilioCallProvider;
      }

      if (
        this.twilioCallProvider.isConfigured() &&
        this.twilioCallProvider.supports(channel)
      ) {
        return this.twilioCallProvider;
      }
    }

    if (channel === Channel.SMS) {
      const configured = this.configService
        .get<string>('SMS_PROVIDER')
        ?.toLowerCase();
      if (configured === 'twilio') {
        if (!this.twilioSmsProvider.supports(channel)) {
          this.logger.warn(
            `SMS_PROVIDER=twilio does not support channel ${channel}`,
          );
          return null;
        }
        return this.twilioSmsProvider;
      }

      if (
        this.twilioSmsProvider.isConfigured() &&
        this.twilioSmsProvider.supports(channel)
      ) {
        return this.twilioSmsProvider;
      }
    }

    return null;
  }
}
