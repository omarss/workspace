export enum Language {
  EN = 'en',
  AR = 'ar',
}

export enum Channel {
  WHATSAPP_TEXT = 'whatsapp_text',
  WHATSAPP_VOICE = 'whatsapp_voice',
  CALL = 'call',
  SMS = 'sms',
}

export enum ConfirmationResult {
  CONFIRMED = 'confirmed',
  REJECTED = 'rejected',
  NOT_CONFIRMED = 'not_confirmed',
}

export interface ConfirmationRequest {
  id: string;
  mobileNumber: string;
  message: string;
  language: Language;
  channel: Channel;
  result: ConfirmationResult;
  provider?: string;
  providerMessageId?: string;
  callbackUrl?: string;
  expiresAt?: string;
  createdAt: string;
  updatedAt: string;
}
