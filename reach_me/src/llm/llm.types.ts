export interface LlmMessage {
  role: 'system' | 'user' | 'assistant';
  content: string;
}

export interface LlmCompletionOptions {
  temperature?: number;
  maxTokens?: number;
}

export interface LlmCompletionResult {
  content: string;
  provider: string;
  model: string;
}

export interface LlmProvider {
  name: string;
  isConfigured(): boolean;
  complete(
    messages: LlmMessage[],
    options?: LlmCompletionOptions,
  ): Promise<LlmCompletionResult>;
}

export const LLM_PROVIDER = Symbol('LLM_PROVIDER');
