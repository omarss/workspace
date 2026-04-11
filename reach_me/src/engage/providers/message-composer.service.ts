import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { LlmService } from '../../llm/llm.service';
import { Language, type Channel, type ConfirmationRequest } from '../types';
import { TranslationService } from './translation.service';

@Injectable()
export class MessageComposerService {
  private readonly logger = new Logger(MessageComposerService.name);
  private readonly rewriteEnabled: boolean;
  private readonly translateEnabled: boolean;

  constructor(
    private readonly configService: ConfigService,
    private readonly llmService: LlmService,
    private readonly translationService: TranslationService,
  ) {
    this.rewriteEnabled =
      this.configService.get<string>('LLM_MESSAGE_REWRITE_ENABLED') === 'true';
    this.translateEnabled =
      this.configService.get<string>('LLM_TRANSLATION_ENABLED') === 'true';
  }

  async compose(
    request: ConfirmationRequest,
    channel: Channel,
  ): Promise<string> {
    let message = request.message;

    if (this.translateEnabled && this.llmService.isConfigured()) {
      message = await this.translationService.detectAndTranslate(
        message,
        request.language,
      );
    }

    if (this.rewriteEnabled && this.llmService.isConfigured()) {
      message = await this.rewriteForChannel(message, request, channel);
    }

    return message;
  }

  private async rewriteForChannel(
    message: string,
    request: ConfirmationRequest,
    channel: Channel,
  ): Promise<string> {
    const languageName = request.language === Language.AR ? 'Arabic' : 'English';

    const systemPrompt = `You are a message composer for a confirmation system.
Rewrite the given message to be clear, concise, and appropriate for the delivery channel.

Requirements:
- Keep the core meaning intact
- Make it suitable for ${this.getChannelDescription(channel)}
- Use ${languageName} language
- Keep it brief and professional
- Return ONLY the rewritten message, nothing else`;

    try {
      const result = await this.llmService.complete(
        [
          { role: 'system', content: systemPrompt },
          { role: 'user', content: message },
        ],
        { temperature: 0.3, maxTokens: 256 },
      );

      return result.content.trim() || message;
    } catch (error) {
      this.logger.warn(`Message rewrite failed: ${(error as Error).message}`);
      return message;
    }
  }

  private getChannelDescription(channel: Channel): string {
    const descriptions: Record<Channel, string> = {
      whatsapp_text: 'WhatsApp text message',
      whatsapp_voice: 'WhatsApp voice note',
      call: 'voice phone call (will be read aloud)',
      sms: 'SMS text message (keep under 160 characters if possible)',
    };

    return descriptions[channel] || 'messaging';
  }
}
