import {
  All,
  Controller,
  Post,
  Query,
  Req,
  Res,
  UnauthorizedException,
} from '@nestjs/common';
import type { Request, Response } from 'express';
import { SkipThrottle } from '@nestjs/throttler';
import { ConfigService } from '@nestjs/config';
import { Public } from '../../../auth/public.decorator';
import { EngageService } from '../../engage.service';
import { LlmConfirmationInterpreter } from '../llm-confirmation-interpreter';
import { VoiceScriptService } from '../voice-script.service';
import { verifyTwilioSignature } from './twilio-signature';

@Controller('webhooks/twilio')
export class TwilioWebhookController {
  constructor(
    private readonly configService: ConfigService,
    private readonly engageService: EngageService,
    private readonly llmInterpreter: LlmConfirmationInterpreter,
    private readonly voiceScriptService: VoiceScriptService,
  ) {}

  @Post('whatsapp/status')
  @Public()
  @SkipThrottle()
  async whatsappStatus(
    @Req() request: Request,
    @Query('requestId') requestId?: string,
  ): Promise<{ status: 'ok' }> {
    this.validateSignature(request);
    const messageSid = this.readParam(request, 'MessageSid');

    if (requestId && messageSid) {
      try {
        await this.engageService.setProviderInfo(
          requestId,
          'twilio_whatsapp',
          messageSid,
        );
      } catch {
        return { status: 'ok' };
      }
    }

    return { status: 'ok' };
  }

  @Post('sms/status')
  @Public()
  @SkipThrottle()
  async smsStatus(
    @Req() request: Request,
    @Query('requestId') requestId?: string,
  ): Promise<{ status: 'ok' }> {
    this.validateSignature(request);
    const messageSid = this.readParam(request, 'MessageSid');

    if (requestId && messageSid) {
      try {
        await this.engageService.setProviderInfo(
          requestId,
          'twilio_sms',
          messageSid,
        );
      } catch {
        return { status: 'ok' };
      }
    }

    return { status: 'ok' };
  }

  @Post('sms/inbound')
  @Public()
  @SkipThrottle()
  async smsInbound(
    @Req() request: Request,
    @Res({ passthrough: true }) response: Response,
  ): Promise<string> {
    this.validateSignature(request);
    response.type('text/xml');

    const body = this.readParam(request, 'Body');
    const result = await this.llmInterpreter.interpret(body);
    if (!result) {
      return this.emptyResponse();
    }

    const requestId = await this.resolveRequestIdFromTwilio(request);
    if (!requestId) {
      return this.emptyResponse();
    }

    await this.engageService.setResult(requestId, result);
    return this.emptyResponse();
  }

  @Post('whatsapp/inbound')
  @Public()
  @SkipThrottle()
  async whatsappInbound(
    @Req() request: Request,
    @Res({ passthrough: true }) response: Response,
  ): Promise<string> {
    this.validateSignature(request);
    response.type('text/xml');

    const body = this.readParam(request, 'Body');
    const result = await this.llmInterpreter.interpret(body);
    if (!result) {
      return this.emptyResponse();
    }

    const requestId = await this.resolveRequestIdFromTwilio(request);
    if (!requestId) {
      return this.emptyResponse();
    }

    await this.engageService.setResult(requestId, result);
    return this.emptyResponse();
  }

  @All('voice')
  @Public()
  @SkipThrottle()
  async voice(
    @Req() request: Request,
    @Res({ passthrough: true }) response: Response,
    @Query('requestId') requestId?: string,
  ): Promise<string> {
    this.validateSignature(request);
    response.type('text/xml');

    if (!requestId) {
      return this.sayResponse('Invalid request.');
    }

    try {
      const confirmation = await this.engageService.get(requestId);
      const script = await this.voiceScriptService.generate(confirmation);
      return this.buildGatherResponse(script, confirmation.language, requestId);
    } catch {
      return this.sayResponse('Invalid request.');
    }
  }

  @Post('voice/confirm')
  @Public()
  @SkipThrottle()
  async voiceConfirm(
    @Req() request: Request,
    @Res({ passthrough: true }) response: Response,
    @Query('requestId') requestId?: string,
  ): Promise<string> {
    this.validateSignature(request);
    response.type('text/xml');

    const digits = this.readParam(request, 'Digits');
    const result = await this.llmInterpreter.interpret(digits);

    if (requestId && result) {
      await this.engageService.setResult(requestId, result);
    }

    return this.sayResponse('Thank you.');
  }

  private validateSignature(request: Request): void {
    const validate =
      this.configService.get<string>('TWILIO_VALIDATE_SIGNATURE') === 'true';
    if (!validate) {
      return;
    }

    const authToken = this.configService.get<string>('TWILIO_AUTH_TOKEN');
    const baseUrl = this.configService.get<string>('PUBLIC_BASE_URL');
    if (!authToken || !baseUrl) {
      throw new UnauthorizedException('Twilio signature config missing');
    }

    const signature = request.header('x-twilio-signature') ?? undefined;
    const url = new URL(request.originalUrl, baseUrl).toString();
    const params = request.body as Record<string, string | string[] | undefined>;
    const valid = verifyTwilioSignature(params, url, signature, authToken);
    if (!valid) {
      throw new UnauthorizedException('Invalid Twilio signature');
    }
  }

  private async resolveRequestIdFromTwilio(
    request: Request,
  ): Promise<string | null> {
    const queryRequestId = request.query.requestId;
    if (typeof queryRequestId === 'string' && queryRequestId) {
      return queryRequestId;
    }

    const repliedMessageId =
      this.readParam(request, 'OriginalRepliedMessageSid') ??
      this.readParam(request, 'OriginalMessageSid');
    if (!repliedMessageId) {
      return null;
    }

    const existing =
      await this.engageService.getByProviderMessageId(repliedMessageId);
    return existing?.id ?? null;
  }

  private readParam(request: Request, key: string): string | null {
    const body = request.body as Record<string, unknown>;
    const value = body[key];
    if (typeof value === 'string') {
      return value;
    }

    return null;
  }

  private emptyResponse(): string {
    return '<?xml version="1.0" encoding="UTF-8"?><Response></Response>';
  }

  private sayResponse(text: string): string {
    return `<?xml version="1.0" encoding="UTF-8"?><Response><Say>${this.escapeXml(
      text,
    )}</Say></Response>`;
  }

  private buildGatherResponse(
    script: string,
    language: string,
    requestId: string,
  ): string {
    const voiceLanguage = language === 'ar' ? 'ar-SA' : 'en-US';
    const actionUrl = this.buildVoiceConfirmUrl(requestId);

    return (
      '<?xml version="1.0" encoding="UTF-8"?>' +
      '<Response>' +
      `<Gather numDigits="1" action="${this.escapeXml(
        actionUrl,
      )}" method="POST" timeout="5">` +
      `<Say language="${voiceLanguage}">${this.escapeXml(script)}</Say>` +
      '</Gather>' +
      '</Response>'
    );
  }

  private buildVoiceConfirmUrl(requestId: string): string {
    const baseUrl = this.configService.get<string>('PUBLIC_BASE_URL');
    if (!baseUrl) {
      return `/webhooks/twilio/voice/confirm?requestId=${encodeURIComponent(
        requestId,
      )}`;
    }

    const url = new URL('/webhooks/twilio/voice/confirm', baseUrl);
    url.searchParams.set('requestId', requestId);
    return url.toString();
  }

  private escapeXml(value: string): string {
    return value
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&apos;');
  }
}
