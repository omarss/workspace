import { Injectable } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import type {
  LlmCompletionOptions,
  LlmCompletionResult,
  LlmMessage,
  LlmProvider,
} from '../llm.types';

interface OllamaMessage {
  role: 'system' | 'user' | 'assistant';
  content: string;
}

interface OllamaResponse {
  message?: {
    content?: string;
  };
}

@Injectable()
export class OllamaProvider implements LlmProvider {
  name = 'ollama';

  constructor(private readonly configService: ConfigService) {}

  isConfigured(): boolean {
    return Boolean(
      this.configService.get<string>('OLLAMA_BASE_URL') &&
        this.configService.get<string>('OLLAMA_MODEL'),
    );
  }

  async complete(
    messages: LlmMessage[],
    options?: LlmCompletionOptions,
  ): Promise<LlmCompletionResult> {
    const baseUrl = this.configService.get<string>('OLLAMA_BASE_URL');
    const model = this.configService.get<string>('OLLAMA_MODEL');

    if (!baseUrl || !model) {
      throw new Error('OLLAMA_BASE_URL and OLLAMA_MODEL must be configured');
    }

    const url = new URL('/api/chat', baseUrl);

    const ollamaMessages: OllamaMessage[] = messages.map((m) => ({
      role: m.role,
      content: m.content,
    }));

    const response = await this.fetchWithTimeout(url.toString(), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model,
        messages: ollamaMessages,
        stream: false,
        options: {
          temperature: options?.temperature ?? 0.3,
          num_predict: options?.maxTokens ?? 512,
        },
      }),
    });

    if (!response.ok) {
      const text = await response.text();
      throw new Error(`Ollama error ${response.status}: ${text.slice(0, 200)}`);
    }

    const data = (await response.json()) as OllamaResponse;
    const content = data.message?.content?.trim() ?? '';

    return { content, provider: this.name, model };
  }

  private async fetchWithTimeout(
    url: string,
    options: RequestInit,
    timeoutMs = 60000,
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
