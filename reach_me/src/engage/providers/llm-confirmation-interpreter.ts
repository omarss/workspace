import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { LlmService } from '../../llm/llm.service';
import { ConfirmationResult } from '../types';
import {
  interpretConfirmation as keywordInterpret,
  type ConfirmationTokens,
} from './confirmation-interpreter';

@Injectable()
export class LlmConfirmationInterpreter {
  private readonly logger = new Logger(LlmConfirmationInterpreter.name);
  private readonly enabled: boolean;

  constructor(
    private readonly configService: ConfigService,
    private readonly llmService: LlmService,
  ) {
    this.enabled =
      this.configService.get<string>('LLM_CONFIRMATION_ENABLED') === 'true';
  }

  async interpret(
    value: string | null | undefined,
    tokens?: ConfirmationTokens,
  ): Promise<ConfirmationResult | null> {
    if (!value) {
      return null;
    }

    const keywordResult = keywordInterpret(value, tokens);
    if (keywordResult !== null) {
      return keywordResult;
    }

    if (!this.enabled || !this.llmService.isConfigured()) {
      return null;
    }

    return this.interpretWithLlm(value);
  }

  private async interpretWithLlm(
    value: string,
  ): Promise<ConfirmationResult | null> {
    const systemPrompt = `You are a confirmation response classifier. Analyze the user's response to a confirmation request and classify it.

Rules:
- If the response indicates agreement, acceptance, or confirmation, respond with exactly: CONFIRMED
- If the response indicates disagreement, rejection, or refusal, respond with exactly: REJECTED
- If the response is unclear, off-topic, or you cannot determine intent, respond with exactly: UNCLEAR

Only respond with one of these three words: CONFIRMED, REJECTED, or UNCLEAR.

Examples:
- "yes" -> CONFIRMED
- "yeah sure" -> CONFIRMED
- "I agree" -> CONFIRMED
- "ok let's do it" -> CONFIRMED
- "absolutely" -> CONFIRMED
- "no" -> REJECTED
- "nope" -> REJECTED
- "cancel it" -> REJECTED
- "I don't want this" -> REJECTED
- "never mind" -> REJECTED
- "what?" -> UNCLEAR
- "tell me more" -> UNCLEAR
- "hello" -> UNCLEAR`;

    try {
      const result = await this.llmService.complete(
        [
          { role: 'system', content: systemPrompt },
          { role: 'user', content: value },
        ],
        { temperature: 0.1, maxTokens: 10 },
      );

      const response = result.content.toUpperCase().trim();

      if (response === 'CONFIRMED') {
        return ConfirmationResult.CONFIRMED;
      }

      if (response === 'REJECTED') {
        return ConfirmationResult.REJECTED;
      }

      return null;
    } catch (error) {
      this.logger.warn(
        `LLM confirmation interpretation failed: ${(error as Error).message}`,
      );
      return null;
    }
  }
}
