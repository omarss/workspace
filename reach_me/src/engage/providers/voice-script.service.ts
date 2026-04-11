import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { LlmService } from '../../llm/llm.service';
import { Language, type ConfirmationRequest } from '../types';

@Injectable()
export class VoiceScriptService {
  private readonly logger = new Logger(VoiceScriptService.name);
  private readonly enabled: boolean;

  constructor(
    private readonly configService: ConfigService,
    private readonly llmService: LlmService,
  ) {
    this.enabled =
      this.configService.get<string>('LLM_VOICE_SCRIPT_ENABLED') === 'true';
  }

  async generate(request: ConfirmationRequest): Promise<string> {
    if (!this.enabled || !this.llmService.isConfigured()) {
      return this.buildDefaultScript(request);
    }

    try {
      return await this.generateWithLlm(request);
    } catch (error) {
      this.logger.warn(
        `Voice script generation failed: ${(error as Error).message}`,
      );
      return this.buildDefaultScript(request);
    }
  }

  private async generateWithLlm(request: ConfirmationRequest): Promise<string> {
    const languageInstructions =
      request.language === Language.AR
        ? 'Generate the script in Arabic (اللغة العربية).'
        : 'Generate the script in English.';

    const systemPrompt = `You are a voice script generator for phone confirmation calls.
Generate a natural, conversational script that will be read by a text-to-speech system.

Requirements:
- Keep it brief and clear (under 100 words)
- Be polite and professional
- ${languageInstructions}
- The script should ask the user to press 1 to confirm or 2 to reject
- Do NOT include any stage directions, just the spoken text
- Make it sound natural when spoken aloud

The user will provide the confirmation message that needs to be delivered.`;

    const result = await this.llmService.complete(
      [
        { role: 'system', content: systemPrompt },
        {
          role: 'user',
          content: `Create a voice script for this confirmation message: "${request.message}"`,
        },
      ],
      { temperature: 0.5, maxTokens: 256 },
    );

    const script = result.content.trim();
    if (!script) {
      return this.buildDefaultScript(request);
    }

    return script;
  }

  private buildDefaultScript(request: ConfirmationRequest): string {
    if (request.language === Language.AR) {
      return `${request.message} اضغط 1 للتأكيد أو 2 للرفض.`;
    }

    return `${request.message} Press 1 to confirm or 2 to reject.`;
  }
}
