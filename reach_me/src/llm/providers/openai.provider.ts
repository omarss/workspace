import { Injectable } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import type {
  LlmCompletionOptions,
  LlmCompletionResult,
  LlmMessage,
  LlmProvider,
} from '../llm.types';

interface OpenAiMessage {
  role: 'system' | 'user' | 'assistant';
  content: string;
}

interface OpenAiResponse {
  choices?: {
    message?: {
      content?: string;
    };
  }[];
}

@Injectable()
export class OpenAiProvider implements LlmProvider {
  name = 'openai';

  constructor(private readonly configService: ConfigService) {}

  isConfigured(): boolean {
    return Boolean(this.configService.get<string>('OPENAI_API_KEY'));
  }

  async complete(
    messages: LlmMessage[],
    options?: LlmCompletionOptions,
  ): Promise<LlmCompletionResult> {
    const apiKey = this.configService.get<string>('OPENAI_API_KEY');
    if (!apiKey) {
      throw new Error('OPENAI_API_KEY not configured');
    }

    const model =
      this.configService.get<string>('OPENAI_MODEL') ?? 'gpt-4o-mini';
    const baseUrl =
      this.configService.get<string>('OPENAI_API_BASE') ??
      'https://api.openai.com';

    const url = new URL('/v1/chat/completions', baseUrl);

    const openAiMessages: OpenAiMessage[] = messages.map((m) => ({
      role: m.role,
      content: m.content,
    }));

    const response = await this.fetchWithTimeout(url.toString(), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${apiKey}`,
      },
      body: JSON.stringify({
        model,
        messages: openAiMessages,
        temperature: options?.temperature ?? 0.3,
        max_tokens: options?.maxTokens ?? 512,
      }),
    });

    if (!response.ok) {
      const text = await response.text();
      throw new Error(`OpenAI error ${response.status}: ${text.slice(0, 200)}`);
    }

    const data = (await response.json()) as OpenAiResponse;
    const content = data.choices?.[0]?.message?.content?.trim() ?? '';

    return { content, provider: this.name, model };
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
