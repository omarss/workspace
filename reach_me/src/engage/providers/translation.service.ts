import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { LlmService } from '../../llm/llm.service';
import type { Language } from '../types';

@Injectable()
export class TranslationService {
  private readonly logger = new Logger(TranslationService.name);
  private readonly enabled: boolean;

  constructor(
    private readonly configService: ConfigService,
    private readonly llmService: LlmService,
  ) {
    this.enabled =
      this.configService.get<string>('LLM_TRANSLATION_ENABLED') === 'true';
  }

  async translate(
    text: string,
    targetLanguage: Language,
    sourceLanguage?: Language,
  ): Promise<string> {
    if (!this.enabled || !this.llmService.isConfigured()) {
      return text;
    }

    if (sourceLanguage === targetLanguage) {
      return text;
    }

    try {
      return await this.translateWithLlm(text, targetLanguage, sourceLanguage);
    } catch (error) {
      this.logger.warn(`Translation failed: ${(error as Error).message}`);
      return text;
    }
  }

  async detectAndTranslate(
    text: string,
    targetLanguage: Language,
  ): Promise<string> {
    if (!this.enabled || !this.llmService.isConfigured()) {
      return text;
    }

    try {
      return await this.detectAndTranslateWithLlm(text, targetLanguage);
    } catch (error) {
      this.logger.warn(
        `Detect and translate failed: ${(error as Error).message}`,
      );
      return text;
    }
  }

  private async translateWithLlm(
    text: string,
    targetLanguage: Language,
    sourceLanguage?: Language,
  ): Promise<string> {
    const targetName = this.getLanguageName(targetLanguage);
    const sourceName = sourceLanguage
      ? this.getLanguageName(sourceLanguage)
      : 'the source language';

    const systemPrompt = `You are a professional translator. Translate the given text from ${sourceName} to ${targetName}.

Rules:
- Maintain the original meaning and tone
- Keep it natural and fluent in the target language
- Preserve any formatting or special characters
- Return ONLY the translated text, nothing else`;

    const result = await this.llmService.complete(
      [
        { role: 'system', content: systemPrompt },
        { role: 'user', content: text },
      ],
      { temperature: 0.2, maxTokens: 512 },
    );

    return result.content.trim() || text;
  }

  private async detectAndTranslateWithLlm(
    text: string,
    targetLanguage: Language,
  ): Promise<string> {
    const targetName = this.getLanguageName(targetLanguage);

    const systemPrompt = `You are a professional translator. Detect the language of the given text and translate it to ${targetName}.

Rules:
- If the text is already in ${targetName}, return it unchanged
- Maintain the original meaning and tone
- Keep it natural and fluent in the target language
- Return ONLY the translated text, nothing else`;

    const result = await this.llmService.complete(
      [
        { role: 'system', content: systemPrompt },
        { role: 'user', content: text },
      ],
      { temperature: 0.2, maxTokens: 512 },
    );

    return result.content.trim() || text;
  }

  private getLanguageName(language: Language): string {
    const names: Record<Language, string> = {
      en: 'English',
      ar: 'Arabic',
    };

    return names[language] || language;
  }
}
