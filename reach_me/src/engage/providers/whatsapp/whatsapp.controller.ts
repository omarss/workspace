import {
  BadRequestException,
  Controller,
  Get,
  Headers,
  Post,
  Query,
  Req,
  UnauthorizedException,
} from '@nestjs/common';
import { SkipThrottle } from '@nestjs/throttler';
import { ConfigService } from '@nestjs/config';
import type { RawBodyRequest } from '../../../common/raw-body-request';
import { Public } from '../../../auth/public.decorator';
import { MetaWhatsAppProvider } from './meta-whatsapp.service';

@Controller('webhooks/whatsapp')
export class WhatsAppWebhookController {
  constructor(
    private readonly configService: ConfigService,
    private readonly provider: MetaWhatsAppProvider,
  ) {}

  @Get()
  @Public()
  @SkipThrottle()
  verify(
    @Query('hub.mode') mode?: string,
    @Query('hub.verify_token') token?: string,
    @Query('hub.challenge') challenge?: string,
  ): string {
    const expected = this.configService.get<string>('WHATSAPP_VERIFY_TOKEN');
    if (!expected) {
      throw new BadRequestException('WHATSAPP_VERIFY_TOKEN is not configured');
    }

    if (mode !== 'subscribe' || token !== expected || !challenge) {
      throw new UnauthorizedException('Invalid verification request');
    }

    return challenge;
  }

  @Post()
  @Public()
  @SkipThrottle()
  async handle(
    @Req() request: RawBodyRequest,
    @Headers('x-hub-signature-256') signature?: string,
  ): Promise<{ status: 'ok'; updates: number }> {
    const rawBody = request.rawBody;
    const appSecret = this.configService.get<string>('WHATSAPP_APP_SECRET');
    if (appSecret) {
      if (!rawBody || !this.provider.verifySignature(rawBody, signature)) {
        throw new UnauthorizedException('Invalid webhook signature');
      }
    }

    const updates = await this.provider.handleWebhook(
      request.body as Parameters<MetaWhatsAppProvider['handleWebhook']>[0],
    );
    return { status: 'ok', updates };
  }
}
