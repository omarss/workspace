import type { Channel } from '../types';
import type { ConfirmationRequest } from '../types';

export type DispatchStatus = 'sent' | 'skipped' | 'failed';

export interface ProviderSendResult {
  provider: string;
  providerMessageId?: string;
  status: DispatchStatus;
}

export interface ChannelProvider {
  name: string;
  supports(channel: Channel): boolean;
  isConfigured(): boolean;
  send(request: ConfirmationRequest, message: string): Promise<ProviderSendResult>;
}
