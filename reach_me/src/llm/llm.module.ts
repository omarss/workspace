import { Global, Module } from '@nestjs/common';
import { LlmService } from './llm.service';
import { GeminiProvider } from './providers/gemini.provider';
import { OpenAiProvider } from './providers/openai.provider';
import { AnthropicProvider } from './providers/anthropic.provider';
import { OllamaProvider } from './providers/ollama.provider';

@Global()
@Module({
  providers: [
    GeminiProvider,
    OpenAiProvider,
    AnthropicProvider,
    OllamaProvider,
    LlmService,
  ],
  exports: [LlmService],
})
export class LlmModule {}
