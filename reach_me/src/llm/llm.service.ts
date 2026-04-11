import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import type {
  LlmCompletionOptions,
  LlmCompletionResult,
  LlmMessage,
  LlmProvider,
} from './llm.types';
import { GeminiProvider } from './providers/gemini.provider';
import { OpenAiProvider } from './providers/openai.provider';
import { AnthropicProvider } from './providers/anthropic.provider';
import { OllamaProvider } from './providers/ollama.provider';

@Injectable()
export class LlmService {
  private readonly logger = new Logger(LlmService.name);
  private readonly providers: Map<string, LlmProvider>;
  private readonly defaultProvider: string | null;

  constructor(
    private readonly configService: ConfigService,
    geminiProvider: GeminiProvider,
    openAiProvider: OpenAiProvider,
    anthropicProvider: AnthropicProvider,
    ollamaProvider: OllamaProvider,
  ) {
    this.providers = new Map<string, LlmProvider>([
      ['gemini', geminiProvider],
      ['openai', openAiProvider],
      ['anthropic', anthropicProvider],
      ['ollama', ollamaProvider],
    ]);

    this.defaultProvider = this.resolveDefaultProvider();
  }

  isConfigured(): boolean {
    return this.defaultProvider !== null;
  }

  getConfiguredProviders(): string[] {
    return Array.from(this.providers.entries())
      .filter(([, provider]) => provider.isConfigured())
      .map(([name]) => name);
  }

  async complete(
    messages: LlmMessage[],
    options?: LlmCompletionOptions & { provider?: string },
  ): Promise<LlmCompletionResult> {
    const providerName = options?.provider ?? this.defaultProvider;
    if (!providerName) {
      throw new Error('No LLM provider configured');
    }

    const provider = this.providers.get(providerName);
    if (!provider) {
      throw new Error(`Unknown LLM provider: ${providerName}`);
    }

    if (!provider.isConfigured()) {
      throw new Error(`LLM provider ${providerName} is not configured`);
    }

    return provider.complete(messages, options);
  }

  async completeWithFallback(
    messages: LlmMessage[],
    options?: LlmCompletionOptions,
  ): Promise<LlmCompletionResult | null> {
    const configured = this.getConfiguredProviders();
    if (configured.length === 0) {
      return null;
    }

    for (const providerName of configured) {
      try {
        return await this.complete(messages, { ...options, provider: providerName });
      } catch (error) {
        this.logger.warn(
          `LLM provider ${providerName} failed: ${(error as Error).message}`,
        );
      }
    }

    return null;
  }

  private resolveDefaultProvider(): string | null {
    const configured = this.configService
      .get<string>('LLM_PROVIDER')
      ?.toLowerCase();

    if (configured && this.providers.has(configured)) {
      const provider = this.providers.get(configured);
      if (provider?.isConfigured()) {
        return configured;
      }
    }

    for (const [name, provider] of this.providers) {
      if (provider.isConfigured()) {
        return name;
      }
    }

    return null;
  }
}
