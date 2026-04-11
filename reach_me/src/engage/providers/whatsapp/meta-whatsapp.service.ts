import { createHmac, timingSafeEqual } from 'node:crypto';
import { GoneException, Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import type { ChannelProvider, ProviderSendResult } from '../provider.types';
import type { ConfirmationTokens } from '../confirmation-interpreter';
import { LlmConfirmationInterpreter } from '../llm-confirmation-interpreter';
import { EngageService } from '../../engage.service';
import { Channel, type ConfirmationRequest } from '../../types';

interface WhatsAppMessage {
  id?: string;
  text?: { body?: string };
  type?: string;
  context?: { id?: string };
  button?: { payload?: string; text?: string };
  interactive?: {
    button_reply?: { id?: string; title?: string };
    list_reply?: { id?: string; title?: string };
  };
}

interface WhatsAppWebhookPayload {
  entry?: {
    changes?: {
      value?: {
        messages?: WhatsAppMessage[];
        statuses?: {
          id?: string;
          status?: string;
          timestamp?: string;
          biz_opaque_callback_data?: string;
        }[];
      };
    }[];
  }[];
}

@Injectable()
export class MetaWhatsAppProvider implements ChannelProvider {
  name = 'meta_whatsapp';
  private readonly logger = new Logger(MetaWhatsAppProvider.name);

  constructor(
    private readonly configService: ConfigService,
    private readonly engageService: EngageService,
    private readonly llmInterpreter: LlmConfirmationInterpreter,
  ) {}

  supports(channel: Channel): boolean {
    return channel === Channel.WHATSAPP_TEXT || channel === Channel.WHATSAPP_VOICE;
  }

  isConfigured(): boolean {
    return Boolean(
      this.configService.get<string>('WHATSAPP_PHONE_NUMBER_ID') &&
        this.configService.get<string>('WHATSAPP_ACCESS_TOKEN'),
    );
  }

  async send(
    request: ConfirmationRequest,
    message: string,
  ): Promise<ProviderSendResult> {
    if (!this.isConfigured()) {
      return { provider: this.name, status: 'skipped' };
    }

    const apiVersion =
      this.configService.get<string>('WHATSAPP_API_VERSION') ?? 'v20.0';
    const phoneNumberId = this.configService.get<string>(
      'WHATSAPP_PHONE_NUMBER_ID',
    );
    const accessToken = this.configService.get<string>(
      'WHATSAPP_ACCESS_TOKEN',
    );

    if (!phoneNumberId || !accessToken) {
      return { provider: this.name, status: 'skipped' };
    }

    const url = `https://graph.facebook.com/${apiVersion}/${phoneNumberId}/messages`;
    const payload = this.buildPayload(request, message);

    const response = await this.fetchWithTimeout(url, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${accessToken}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      const text = await response.text();
      throw new Error(
        `Meta WhatsApp error ${response.status}: ${text.slice(0, 200)}`,
      );
    }

    const data = (await response.json()) as {
      messages?: { id?: string }[];
    };
    const messageId = data.messages?.[0]?.id;

    return {
      provider: this.name,
      providerMessageId: messageId,
      status: 'sent',
    };
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

  async handleWebhook(payload: WhatsAppWebhookPayload): Promise<number> {
    let updates = 0;

    for (const entry of payload.entry ?? []) {
      for (const change of entry.changes ?? []) {
        const value = change.value;
        if (!value) {
          continue;
        }

        for (const status of value.statuses ?? []) {
          const requestId = status.biz_opaque_callback_data;
          const messageId = status.id;
          if (requestId && messageId) {
            try {
              await this.engageService.setProviderInfo(
                requestId,
                this.name,
                messageId,
              );
            } catch (error) {
              this.logger.warn(
                `Failed to map status to request ${requestId}: ${
                  (error as Error).message
                }`,
              );
            }
          }
        }

        for (const message of value.messages ?? []) {
          const result = await this.extractResult(message);
          if (!result) {
            continue;
          }

          const requestId = await this.resolveRequestId(message);
          if (!requestId) {
            this.logger.warn('WhatsApp reply could not be mapped to a request');
            continue;
          }

          try {
            await this.engageService.setResult(requestId, result);
            updates += 1;
          } catch (error) {
            if (error instanceof GoneException) {
              this.logger.warn(`Request ${requestId} has expired`);
              continue;
            }
            throw error;
          }
        }
      }
    }

    return updates;
  }

  verifySignature(rawBody: Buffer, signature: string | undefined): boolean {
    const secret = this.configService.get<string>('WHATSAPP_APP_SECRET');
    if (!secret) {
      return true;
    }

    if (!signature) {
      return false;
    }

    const expected = createHmac('sha256', secret)
      .update(rawBody)
      .digest('hex');
    const expectedHeader = `sha256=${expected}`;

    if (expectedHeader.length !== signature.length) {
      return false;
    }

    return timingSafeEqual(
      Buffer.from(expectedHeader, 'utf8'),
      Buffer.from(signature, 'utf8'),
    );
  }

  private buildPayload(request: ConfirmationRequest, message: string) {
    if (request.channel === Channel.WHATSAPP_VOICE) {
      const voiceMode =
        this.configService.get<string>('WHATSAPP_VOICE_MODE')?.toLowerCase() ??
        'text';
      if (voiceMode === 'audio_link') {
        const mediaUrl = this.configService.get<string>(
          'WHATSAPP_VOICE_MEDIA_URL',
        );
        if (mediaUrl) {
          return {
            messaging_product: 'whatsapp',
            to: request.mobileNumber,
            type: 'audio',
            audio: { link: mediaUrl },
            biz_opaque_callback_data: request.id,
          };
        }
      }

      if (voiceMode === 'audio_id') {
        const mediaId = this.configService.get<string>(
          'WHATSAPP_VOICE_MEDIA_ID',
        );
        if (mediaId) {
          return {
            messaging_product: 'whatsapp',
            to: request.mobileNumber,
            type: 'audio',
            audio: { id: mediaId },
            biz_opaque_callback_data: request.id,
          };
        }
      }
    }

    const mode = this.configService
      .get<string>('WHATSAPP_MESSAGE_MODE')
      ?.toLowerCase();
    if (mode === 'interactive') {
      const payload = this.buildInteractivePayload(request, message);
      if (payload) {
        return payload;
      }
    }

    if (mode === 'template') {
      const payload = this.buildTemplatePayload(request, message);
      if (payload) {
        return payload;
      }
    }

    return {
      messaging_product: 'whatsapp',
      to: request.mobileNumber,
      type: 'text',
      text: { body: message },
      biz_opaque_callback_data: request.id,
    };
  }

  private buildInteractivePayload(
    request: ConfirmationRequest,
    message: string,
  ) {
    if (request.channel !== Channel.WHATSAPP_TEXT) {
      return null;
    }

    const labels = this.resolveButtonLabels(request.language);
    const payloads = this.resolveButtonPayloads();

    return {
      messaging_product: 'whatsapp',
      to: request.mobileNumber,
      type: 'interactive',
      interactive: {
        type: 'button',
        body: { text: message },
        action: {
          buttons: [
            {
              type: 'reply',
              reply: { id: payloads.confirm, title: labels.confirm },
            },
            {
              type: 'reply',
              reply: { id: payloads.reject, title: labels.reject },
            },
          ],
        },
      },
      biz_opaque_callback_data: request.id,
    };
  }

  private buildTemplatePayload(request: ConfirmationRequest, message: string) {
    if (request.channel !== Channel.WHATSAPP_TEXT) {
      return null;
    }

    const templateName = this.configService.get<string>(
      'WHATSAPP_TEMPLATE_NAME',
    );
    if (!templateName) {
      this.logger.warn('WHATSAPP_TEMPLATE_NAME is not configured');
      return null;
    }

    const components: Record<string, unknown>[] = [];
    const bodyParamMode =
      this.configService.get<string>('WHATSAPP_TEMPLATE_BODY_PARAM')?.toLowerCase() ??
      'message';
    if (bodyParamMode !== 'none') {
      components.push({
        type: 'body',
        parameters: [{ type: 'text', text: message }],
      });
    }

    const buttonMode =
      this.configService.get<string>('WHATSAPP_TEMPLATE_BUTTONS')?.toLowerCase() ??
      'confirm_reject';
    if (buttonMode !== 'none') {
      const payloads = this.resolveButtonPayloads();
      components.push(
        {
          type: 'button',
          sub_type: 'quick_reply',
          index: '0',
          parameters: [{ type: 'payload', payload: payloads.confirm }],
        },
        {
          type: 'button',
          sub_type: 'quick_reply',
          index: '1',
          parameters: [{ type: 'payload', payload: payloads.reject }],
        },
      );
    }

    return {
      messaging_product: 'whatsapp',
      to: request.mobileNumber,
      type: 'template',
      template: {
        name: templateName,
        language: { code: this.resolveTemplateLanguage(request.language) },
        components,
      },
      biz_opaque_callback_data: request.id,
    };
  }

  private resolveButtonLabels(language: string): {
    confirm: string;
    reject: string;
  } {
    const isArabic = language === 'ar';
    const confirm =
      this.configService.get<string>(
        isArabic ? 'WHATSAPP_CONFIRM_LABEL_AR' : 'WHATSAPP_CONFIRM_LABEL_EN',
      ) ?? 'Confirm';
    const reject =
      this.configService.get<string>(
        isArabic ? 'WHATSAPP_REJECT_LABEL_AR' : 'WHATSAPP_REJECT_LABEL_EN',
      ) ?? 'Reject';

    return { confirm, reject };
  }

  private resolveButtonPayloads(): { confirm: string; reject: string } {
    const confirm =
      this.configService.get<string>('WHATSAPP_CONFIRM_PAYLOAD') ?? 'confirm';
    const reject =
      this.configService.get<string>('WHATSAPP_REJECT_PAYLOAD') ?? 'reject';
    return { confirm, reject };
  }

  private resolveTemplateLanguage(language: string): string {
    const fallback = this.configService.get<string>('WHATSAPP_TEMPLATE_LANGUAGE');
    if (language === 'ar') {
      return (
        this.configService.get<string>('WHATSAPP_TEMPLATE_LANGUAGE_AR') ??
        fallback ??
        'ar'
      );
    }

    if (language === 'en') {
      return (
        this.configService.get<string>('WHATSAPP_TEMPLATE_LANGUAGE_EN') ??
        fallback ??
        'en_US'
      );
    }

    return fallback ?? language;
  }

  private async extractResult(message: WhatsAppMessage) {
    const tokens = this.buildConfirmationTokens();

    if (message.text?.body) {
      return this.llmInterpreter.interpret(message.text.body, tokens);
    }

    if (message.button?.payload) {
      return this.llmInterpreter.interpret(message.button.payload, tokens);
    }

    const interactive = message.interactive;
    if (interactive?.button_reply?.id) {
      return this.llmInterpreter.interpret(interactive.button_reply.id, tokens);
    }

    if (interactive?.button_reply?.title) {
      return this.llmInterpreter.interpret(interactive.button_reply.title, tokens);
    }

    if (interactive?.list_reply?.id) {
      return this.llmInterpreter.interpret(interactive.list_reply.id, tokens);
    }

    if (interactive?.list_reply?.title) {
      return this.llmInterpreter.interpret(interactive.list_reply.title, tokens);
    }

    return null;
  }

  private buildConfirmationTokens(): ConfirmationTokens {
    const payloads = this.resolveButtonPayloads();
    const labelsEn = this.resolveButtonLabels('en');
    const labelsAr = this.resolveButtonLabels('ar');

    return {
      confirm: [payloads.confirm, labelsEn.confirm, labelsAr.confirm],
      reject: [payloads.reject, labelsEn.reject, labelsAr.reject],
    };
  }

  private async resolveRequestId(message: {
    context?: { id?: string };
  }): Promise<string | null> {
    const contextId = message.context?.id;
    if (!contextId) {
      return null;
    }

    const existing = await this.engageService.getByProviderMessageId(contextId);
    return existing?.id ?? null;
  }
}
