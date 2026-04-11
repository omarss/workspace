import { Injectable } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import type {
  LlmCompletionOptions,
  LlmCompletionResult,
  LlmMessage,
  LlmProvider,
} from '../llm.types';

interface GeminiContent {
  role: string;
  parts: { text: string }[];
}

interface GeminiResponse {
  candidates?: {
    content?: {
      parts?: { text?: string }[];
    };
  }[];
}

@Injectable()
export class GeminiProvider implements LlmProvider {
  name = 'gemini';

  constructor(private readonly configService: ConfigService) {}

  isConfigured(): boolean {
    return Boolean(this.configService.get<string>('GEMINI_API_KEY'));
  }

  async complete(
    messages: LlmMessage[],
    options?: LlmCompletionOptions,
  ): Promise<LlmCompletionResult> {
    const apiKey = this.configService.get<string>('GEMINI_API_KEY');
    if (!apiKey) {
      throw new Error('GEMINI_API_KEY not configured');
    }

    const model =
      this.configService.get<string>('GEMINI_MODEL') ?? 'gemini-1.5-flash';
    const baseUrl =
      this.configService.get<string>('GEMINI_API_BASE') ??
      'https://generativelanguage.googleapis.com';

    const url = new URL(`/v1beta/models/${model}:generateContent`, baseUrl);
    url.searchParams.set('key', apiKey);

    const contents = this.convertMessages(messages);

    const response = await this.fetchWithTimeout(url.toString(), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        contents,
        generationConfig: {
          temperature: options?.temperature ?? 0.3,
          maxOutputTokens: options?.maxTokens ?? 512,
        },
      }),
    });

    if (!response.ok) {
      const text = await response.text();
      throw new Error(`Gemini error ${response.status}: ${text.slice(0, 200)}`);
    }

    const data = (await response.json()) as GeminiResponse;
    const content =
      data.candidates?.[0]?.content?.parts?.[0]?.text?.trim() ?? '';

    return { content, provider: this.name, model };
  }

  private convertMessages(messages: LlmMessage[]): GeminiContent[] {
    const contents: GeminiContent[] = [];
    let systemPrompt = '';

    for (const msg of messages) {
      if (msg.role === 'system') {
        systemPrompt += msg.content + '\n';
      } else {
        const role = msg.role === 'assistant' ? 'model' : 'user';
        contents.push({ role, parts: [{ text: msg.content }] });
      }
    }

    if (systemPrompt && contents.length > 0 && contents[0].role === 'user') {
      contents[0].parts[0].text =
        systemPrompt.trim() + '\n\n' + contents[0].parts[0].text;
    }

    return contents;
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
