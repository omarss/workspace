import { Injectable } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import type {
  LlmCompletionOptions,
  LlmCompletionResult,
  LlmMessage,
  LlmProvider,
} from '../llm.types';

interface AnthropicMessage {
  role: 'user' | 'assistant';
  content: string;
}

interface AnthropicResponse {
  content?: {
    type: string;
    text?: string;
  }[];
}

@Injectable()
export class AnthropicProvider implements LlmProvider {
  name = 'anthropic';

  constructor(private readonly configService: ConfigService) {}

  isConfigured(): boolean {
    return Boolean(this.configService.get<string>('ANTHROPIC_API_KEY'));
  }

  async complete(
    messages: LlmMessage[],
    options?: LlmCompletionOptions,
  ): Promise<LlmCompletionResult> {
    const apiKey = this.configService.get<string>('ANTHROPIC_API_KEY');
    if (!apiKey) {
      throw new Error('ANTHROPIC_API_KEY not configured');
    }

    const model =
      this.configService.get<string>('ANTHROPIC_MODEL') ??
      'claude-3-5-haiku-latest';
    const baseUrl =
      this.configService.get<string>('ANTHROPIC_API_BASE') ??
      'https://api.anthropic.com';

    const url = new URL('/v1/messages', baseUrl);

    const { systemPrompt, anthropicMessages } = this.convertMessages(messages);

    const body: Record<string, unknown> = {
      model,
      messages: anthropicMessages,
      max_tokens: options?.maxTokens ?? 512,
      temperature: options?.temperature ?? 0.3,
    };

    if (systemPrompt) {
      body.system = systemPrompt;
    }

    const response = await this.fetchWithTimeout(url.toString(), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'x-api-key': apiKey,
        'anthropic-version': '2023-06-01',
      },
      body: JSON.stringify(body),
    });

    if (!response.ok) {
      const text = await response.text();
      throw new Error(
        `Anthropic error ${response.status}: ${text.slice(0, 200)}`,
      );
    }

    const data = (await response.json()) as AnthropicResponse;
    const textBlock = data.content?.find((c) => c.type === 'text');
    const content = textBlock?.text?.trim() ?? '';

    return { content, provider: this.name, model };
  }

  private convertMessages(messages: LlmMessage[]): {
    systemPrompt: string;
    anthropicMessages: AnthropicMessage[];
  } {
    let systemPrompt = '';
    const anthropicMessages: AnthropicMessage[] = [];

    for (const msg of messages) {
      if (msg.role === 'system') {
        systemPrompt += msg.content + '\n';
      } else {
        anthropicMessages.push({
          role: msg.role === 'user' ? 'user' : 'assistant',
          content: msg.content,
        });
      }
    }

    return { systemPrompt: systemPrompt.trim(), anthropicMessages };
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
