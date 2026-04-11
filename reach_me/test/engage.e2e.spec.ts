import { afterAll, beforeAll, describe, expect, it } from 'bun:test';
import { ValidationPipe } from '@nestjs/common';
import { Test } from '@nestjs/testing';
import type { NestExpressApplication } from '@nestjs/platform-express';
import type { Server } from 'node:http';
import request from 'supertest';
import { AppModule } from '../src/app.module';
import type { RawBodyRequest } from '../src/common/raw-body-request';

describe('EngageController (e2e)', () => {
  let app: NestExpressApplication;
  let server: Server;

  beforeAll(async () => {
    process.env.ENGAGE_STORE = 'memory';
    delete process.env.API_KEY;
    process.env.WHATSAPP_PROVIDER = '';
    process.env.WHATSAPP_PHONE_NUMBER_ID = '';
    process.env.WHATSAPP_ACCESS_TOKEN = '';
    process.env.CALL_PROVIDER = '';
    process.env.TWILIO_ACCOUNT_SID = '';
    process.env.TWILIO_AUTH_TOKEN = '';
    process.env.TWILIO_WHATSAPP_FROM = '';
    process.env.TWILIO_CALL_FROM = '';
    process.env.PUBLIC_BASE_URL = '';
    process.env.SLACK_WEBHOOK_URL = '';
    process.env.AI_MESSAGE_PROVIDER = '';
    process.env.WHATSAPP_CONFIRM_PAYLOAD = 'approve_me';
    process.env.WHATSAPP_REJECT_PAYLOAD = 'deny_me';
    process.env.WHATSAPP_CONFIRM_LABEL_EN = 'Approve';
    process.env.WHATSAPP_REJECT_LABEL_EN = 'Deny';
    process.env.WHATSAPP_CONFIRM_LABEL_AR = 'Confirm_AR';
    process.env.WHATSAPP_REJECT_LABEL_AR = 'Reject_AR';
    delete process.env.WHATSAPP_APP_SECRET;
    process.env.PG_BOSS_CONNECTION_STRING = '';
    process.env.DATABASE_URL = '';
    process.env.PG_BOSS_WORKER_ENABLED = 'false';

    const moduleRef = await Test.createTestingModule({
      imports: [AppModule],
    }).compile();

    app = moduleRef.createNestApplication<NestExpressApplication>();
    app.useBodyParser('json', {
      verify: (req: RawBodyRequest, _res: unknown, buf: Buffer) => {
        req.rawBody = buf;
      },
    });
    app.useGlobalPipes(
      new ValidationPipe({
        whitelist: true,
        forbidNonWhitelisted: true,
        transform: true,
      }),
    );
    await app.init();
    server = app.getHttpServer() as Server;
  });

  afterAll(async () => {
    await app.close();
  });

  it('health ok', async () => {
    await request(server).get('/health').expect(200).expect({
      status: 'ok',
    });
  });

  it('creates a confirmation request', async () => {
    const res = await request(server)
      .post('/v1/engage')
      .send({
        mobileNumber: '+201234567890',
        message: 'hello',
        language: 'en',
        channel: 'whatsapp_text',
      })
      .expect(201);

    const body = res.body as { requestId: string; result: string };
    expect(body.requestId).toBeTruthy();
    expect(body.result).toBe('not_confirmed');
  });

  it('rejects invalid payloads', async () => {
    await request(server)
      .post('/v1/engage')
      .send({
        mobileNumber: '12345',
        message: 'hello',
        language: 'en',
        channel: 'whatsapp_text',
      })
      .expect(400);
  });

  it('returns not found for missing request', async () => {
    await request(server).get('/v1/engage/missing').expect(404);
  });

  it('accepts custom WhatsApp confirm payloads', async () => {
    const res = await request(server)
      .post('/v1/engage')
      .send({
        mobileNumber: '+201234567891',
        message: 'custom payload test',
        language: 'en',
        channel: 'whatsapp_text',
      })
      .expect(201);

    const { requestId } = res.body as { requestId: string };
    const providerMessageId = 'wa-msg-123';

    await request(server)
      .post('/webhooks/whatsapp')
      .send({
        entry: [
          {
            changes: [
              {
                value: {
                  statuses: [
                    {
                      id: providerMessageId,
                      biz_opaque_callback_data: requestId,
                    },
                  ],
                  messages: [
                    {
                      context: { id: providerMessageId },
                      text: { body: 'approve_me' },
                    },
                  ],
                },
              },
            ],
          },
        ],
      })
      .expect(201);

    const updated = await request(server)
      .get(`/v1/engage/${requestId}`)
      .expect(200);

    expect(updated.body.result).toBe('confirmed');
  });
});

describe('SMS channel (e2e)', () => {
  let app: NestExpressApplication;
  let server: Server;

  beforeAll(async () => {
    process.env.ENGAGE_STORE = 'memory';
    delete process.env.API_KEY;
    process.env.WHATSAPP_PROVIDER = '';
    process.env.WHATSAPP_PHONE_NUMBER_ID = '';
    process.env.WHATSAPP_ACCESS_TOKEN = '';
    process.env.CALL_PROVIDER = '';
    process.env.SMS_PROVIDER = '';
    process.env.TWILIO_ACCOUNT_SID = '';
    process.env.TWILIO_AUTH_TOKEN = '';
    process.env.TWILIO_WHATSAPP_FROM = '';
    process.env.TWILIO_CALL_FROM = '';
    process.env.TWILIO_SMS_FROM = '';
    process.env.PUBLIC_BASE_URL = '';
    process.env.SLACK_WEBHOOK_URL = '';
    process.env.PG_BOSS_CONNECTION_STRING = '';
    process.env.DATABASE_URL = '';
    process.env.PG_BOSS_WORKER_ENABLED = 'false';
    process.env.TWILIO_VALIDATE_SIGNATURE = 'false';

    const moduleRef = await Test.createTestingModule({
      imports: [AppModule],
    }).compile();

    app = moduleRef.createNestApplication<NestExpressApplication>();
    app.useBodyParser('json', {
      verify: (req: RawBodyRequest, _res: unknown, buf: Buffer) => {
        req.rawBody = buf;
      },
    });
    app.useBodyParser('urlencoded', { extended: true });
    app.useGlobalPipes(
      new ValidationPipe({
        whitelist: true,
        forbidNonWhitelisted: true,
        transform: true,
      }),
    );
    await app.init();
    server = app.getHttpServer() as Server;
  });

  afterAll(async () => {
    await app.close();
  });

  it('creates an SMS confirmation request', async () => {
    const res = await request(server)
      .post('/v1/engage')
      .send({
        mobileNumber: '+201234567892',
        message: 'SMS test message',
        language: 'en',
        channel: 'sms',
      })
      .expect(201);

    const body = res.body as { requestId: string; result: string };
    expect(body.requestId).toBeTruthy();
    expect(body.result).toBe('not_confirmed');
  });

  it('handles Twilio SMS status webhook', async () => {
    const res = await request(server)
      .post('/v1/engage')
      .send({
        mobileNumber: '+201234567893',
        message: 'SMS status test',
        language: 'en',
        channel: 'sms',
      })
      .expect(201);

    const { requestId } = res.body as { requestId: string };

    await request(server)
      .post(`/webhooks/twilio/sms/status?requestId=${requestId}`)
      .type('form')
      .send({
        MessageSid: 'SM123456789',
        MessageStatus: 'delivered',
      })
      .expect(201);

    const updated = await request(server)
      .get(`/v1/engage/${requestId}`)
      .expect(200);

    expect(updated.body.providerMessageId).toBe('SM123456789');
  });

  it('handles Twilio SMS inbound webhook with confirmation', async () => {
    const res = await request(server)
      .post('/v1/engage')
      .send({
        mobileNumber: '+201234567894',
        message: 'SMS inbound test',
        language: 'en',
        channel: 'sms',
      })
      .expect(201);

    const { requestId } = res.body as { requestId: string };
    const messageSid = 'SM-inbound-123';

    // First set the provider message ID via status webhook
    await request(server)
      .post(`/webhooks/twilio/sms/status?requestId=${requestId}`)
      .type('form')
      .send({
        MessageSid: messageSid,
        MessageStatus: 'delivered',
      })
      .expect(201);

    // Then simulate inbound reply using OriginalRepliedMessageSid
    const inboundRes = await request(server)
      .post('/webhooks/twilio/sms/inbound')
      .type('form')
      .send({
        Body: 'yes',
        OriginalRepliedMessageSid: messageSid,
      })
      .expect(201);

    expect(inboundRes.text).toContain('<Response>');

    const updated = await request(server)
      .get(`/v1/engage/${requestId}`)
      .expect(200);

    expect(updated.body.result).toBe('confirmed');
  });

  it('handles SMS rejection', async () => {
    const res = await request(server)
      .post('/v1/engage')
      .send({
        mobileNumber: '+201234567895',
        message: 'SMS rejection test',
        language: 'en',
        channel: 'sms',
      })
      .expect(201);

    const { requestId } = res.body as { requestId: string };

    // Use requestId query param for direct mapping
    await request(server)
      .post(`/webhooks/twilio/sms/inbound?requestId=${requestId}`)
      .type('form')
      .send({
        Body: 'no',
      })
      .expect(201);

    const updated = await request(server)
      .get(`/v1/engage/${requestId}`)
      .expect(200);

    expect(updated.body.result).toBe('rejected');
  });
});

describe('Voice/Call channel (e2e)', () => {
  let app: NestExpressApplication;
  let server: Server;

  beforeAll(async () => {
    process.env.ENGAGE_STORE = 'memory';
    delete process.env.API_KEY;
    process.env.WHATSAPP_PROVIDER = '';
    process.env.WHATSAPP_PHONE_NUMBER_ID = '';
    process.env.WHATSAPP_ACCESS_TOKEN = '';
    process.env.CALL_PROVIDER = '';
    process.env.TWILIO_ACCOUNT_SID = '';
    process.env.TWILIO_AUTH_TOKEN = '';
    process.env.TWILIO_WHATSAPP_FROM = '';
    process.env.TWILIO_CALL_FROM = '';
    process.env.PUBLIC_BASE_URL = 'http://localhost:3000';
    process.env.SLACK_WEBHOOK_URL = '';
    process.env.PG_BOSS_CONNECTION_STRING = '';
    process.env.DATABASE_URL = '';
    process.env.PG_BOSS_WORKER_ENABLED = 'false';
    process.env.TWILIO_VALIDATE_SIGNATURE = 'false';
    process.env.LLM_VOICE_SCRIPT_ENABLED = 'false';

    const moduleRef = await Test.createTestingModule({
      imports: [AppModule],
    }).compile();

    app = moduleRef.createNestApplication<NestExpressApplication>();
    app.useBodyParser('json', {
      verify: (req: RawBodyRequest, _res: unknown, buf: Buffer) => {
        req.rawBody = buf;
      },
    });
    app.useBodyParser('urlencoded', { extended: true });
    app.useGlobalPipes(
      new ValidationPipe({
        whitelist: true,
        forbidNonWhitelisted: true,
        transform: true,
      }),
    );
    await app.init();
    server = app.getHttpServer() as Server;
  });

  afterAll(async () => {
    await app.close();
  });

  it('creates a call confirmation request', async () => {
    const res = await request(server)
      .post('/v1/engage')
      .send({
        mobileNumber: '+201234567896',
        message: 'Call test message',
        language: 'en',
        channel: 'call',
      })
      .expect(201);

    const body = res.body as { requestId: string; result: string };
    expect(body.requestId).toBeTruthy();
    expect(body.result).toBe('not_confirmed');
  });

  it('handles Twilio voice webhook and returns TwiML', async () => {
    const res = await request(server)
      .post('/v1/engage')
      .send({
        mobileNumber: '+201234567897',
        message: 'Voice TwiML test',
        language: 'en',
        channel: 'call',
      })
      .expect(201);

    const { requestId } = res.body as { requestId: string };

    const voiceRes = await request(server)
      .post(`/webhooks/twilio/voice?requestId=${requestId}`)
      .type('form')
      .send({
        CallSid: 'CA123456789',
      })
      .expect(200);

    expect(voiceRes.text).toContain('<Response>');
    expect(voiceRes.text).toContain('<Gather');
    expect(voiceRes.text).toContain('<Say');
    expect(voiceRes.text).toContain('Voice TwiML test');
    expect(voiceRes.text).toContain('Press 1 to confirm or 2 to reject');
  });

  it('handles Arabic voice script', async () => {
    const res = await request(server)
      .post('/v1/engage')
      .send({
        mobileNumber: '+201234567898',
        message: 'رسالة اختبار',
        language: 'ar',
        channel: 'call',
      })
      .expect(201);

    const { requestId } = res.body as { requestId: string };

    const voiceRes = await request(server)
      .post(`/webhooks/twilio/voice?requestId=${requestId}`)
      .type('form')
      .send({
        CallSid: 'CA123456790',
      })
      .expect(200);

    expect(voiceRes.text).toContain('language="ar-SA"');
    expect(voiceRes.text).toContain('اضغط 1 للتأكيد أو 2 للرفض');
  });

  it('handles voice confirm webhook with digit 1 (confirm)', async () => {
    const res = await request(server)
      .post('/v1/engage')
      .send({
        mobileNumber: '+201234567899',
        message: 'Voice confirm test',
        language: 'en',
        channel: 'call',
      })
      .expect(201);

    const { requestId } = res.body as { requestId: string };

    const confirmRes = await request(server)
      .post(`/webhooks/twilio/voice/confirm?requestId=${requestId}`)
      .type('form')
      .send({
        Digits: '1',
      })
      .expect(201);

    expect(confirmRes.text).toContain('<Say>Thank you.</Say>');

    const updated = await request(server)
      .get(`/v1/engage/${requestId}`)
      .expect(200);

    expect(updated.body.result).toBe('confirmed');
  });

  it('handles voice confirm webhook with digit 2 (reject)', async () => {
    const res = await request(server)
      .post('/v1/engage')
      .send({
        mobileNumber: '+201234567900',
        message: 'Voice reject test',
        language: 'en',
        channel: 'call',
      })
      .expect(201);

    const { requestId } = res.body as { requestId: string };

    await request(server)
      .post(`/webhooks/twilio/voice/confirm?requestId=${requestId}`)
      .type('form')
      .send({
        Digits: '2',
      })
      .expect(201);

    const updated = await request(server)
      .get(`/v1/engage/${requestId}`)
      .expect(200);

    expect(updated.body.result).toBe('rejected');
  });

  it('returns error for voice webhook without requestId', async () => {
    const voiceRes = await request(server)
      .post('/webhooks/twilio/voice')
      .type('form')
      .send({
        CallSid: 'CA-invalid',
      })
      .expect(200);

    expect(voiceRes.text).toContain('Invalid request');
  });
});

describe('WhatsApp rejection flow (e2e)', () => {
  let app: NestExpressApplication;
  let server: Server;

  beforeAll(async () => {
    process.env.ENGAGE_STORE = 'memory';
    delete process.env.API_KEY;
    process.env.WHATSAPP_PROVIDER = '';
    process.env.WHATSAPP_PHONE_NUMBER_ID = '';
    process.env.WHATSAPP_ACCESS_TOKEN = '';
    process.env.WHATSAPP_CONFIRM_PAYLOAD = 'yes_confirm';
    process.env.WHATSAPP_REJECT_PAYLOAD = 'no_reject';
    delete process.env.WHATSAPP_APP_SECRET;
    process.env.PG_BOSS_CONNECTION_STRING = '';
    process.env.DATABASE_URL = '';
    process.env.PG_BOSS_WORKER_ENABLED = 'false';

    const moduleRef = await Test.createTestingModule({
      imports: [AppModule],
    }).compile();

    app = moduleRef.createNestApplication<NestExpressApplication>();
    app.useBodyParser('json', {
      verify: (req: RawBodyRequest, _res: unknown, buf: Buffer) => {
        req.rawBody = buf;
      },
    });
    app.useGlobalPipes(
      new ValidationPipe({
        whitelist: true,
        forbidNonWhitelisted: true,
        transform: true,
      }),
    );
    await app.init();
    server = app.getHttpServer() as Server;
  });

  afterAll(async () => {
    await app.close();
  });

  it('handles WhatsApp rejection via text reply', async () => {
    const res = await request(server)
      .post('/v1/engage')
      .send({
        mobileNumber: '+201234567901',
        message: 'WhatsApp rejection test',
        language: 'en',
        channel: 'whatsapp_text',
      })
      .expect(201);

    const { requestId } = res.body as { requestId: string };
    const providerMessageId = 'wa-reject-123';

    await request(server)
      .post('/webhooks/whatsapp')
      .send({
        entry: [
          {
            changes: [
              {
                value: {
                  statuses: [
                    {
                      id: providerMessageId,
                      biz_opaque_callback_data: requestId,
                    },
                  ],
                  messages: [
                    {
                      context: { id: providerMessageId },
                      text: { body: 'no_reject' },
                    },
                  ],
                },
              },
            ],
          },
        ],
      })
      .expect(201);

    const updated = await request(server)
      .get(`/v1/engage/${requestId}`)
      .expect(200);

    expect(updated.body.result).toBe('rejected');
  });

  it('handles WhatsApp interactive button reply', async () => {
    const res = await request(server)
      .post('/v1/engage')
      .send({
        mobileNumber: '+201234567902',
        message: 'Interactive button test',
        language: 'en',
        channel: 'whatsapp_text',
      })
      .expect(201);

    const { requestId } = res.body as { requestId: string };
    const providerMessageId = 'wa-interactive-123';

    await request(server)
      .post('/webhooks/whatsapp')
      .send({
        entry: [
          {
            changes: [
              {
                value: {
                  statuses: [
                    {
                      id: providerMessageId,
                      biz_opaque_callback_data: requestId,
                    },
                  ],
                  messages: [
                    {
                      context: { id: providerMessageId },
                      interactive: {
                        button_reply: {
                          id: 'yes_confirm',
                          title: 'Confirm',
                        },
                      },
                    },
                  ],
                },
              },
            ],
          },
        ],
      })
      .expect(201);

    const updated = await request(server)
      .get(`/v1/engage/${requestId}`)
      .expect(200);

    expect(updated.body.result).toBe('confirmed');
  });

  it('handles WhatsApp button payload reply', async () => {
    const res = await request(server)
      .post('/v1/engage')
      .send({
        mobileNumber: '+201234567903',
        message: 'Button payload test',
        language: 'en',
        channel: 'whatsapp_text',
      })
      .expect(201);

    const { requestId } = res.body as { requestId: string };
    const providerMessageId = 'wa-button-123';

    await request(server)
      .post('/webhooks/whatsapp')
      .send({
        entry: [
          {
            changes: [
              {
                value: {
                  statuses: [
                    {
                      id: providerMessageId,
                      biz_opaque_callback_data: requestId,
                    },
                  ],
                  messages: [
                    {
                      context: { id: providerMessageId },
                      button: {
                        payload: 'no_reject',
                        text: 'Reject',
                      },
                    },
                  ],
                },
              },
            ],
          },
        ],
      })
      .expect(201);

    const updated = await request(server)
      .get(`/v1/engage/${requestId}`)
      .expect(200);

    expect(updated.body.result).toBe('rejected');
  });
});

describe('Confirmation expiry (e2e)', () => {
  let app: NestExpressApplication;
  let server: Server;

  beforeAll(async () => {
    process.env.ENGAGE_STORE = 'memory';
    delete process.env.API_KEY;
    process.env.WHATSAPP_PROVIDER = '';
    process.env.WHATSAPP_PHONE_NUMBER_ID = '';
    process.env.WHATSAPP_ACCESS_TOKEN = '';
    delete process.env.WHATSAPP_APP_SECRET;
    process.env.PG_BOSS_CONNECTION_STRING = '';
    process.env.DATABASE_URL = '';
    process.env.PG_BOSS_WORKER_ENABLED = 'false';
    process.env.CONFIRMATION_TTL_SECONDS = '1'; // 1 second TTL for testing

    const moduleRef = await Test.createTestingModule({
      imports: [AppModule],
    }).compile();

    app = moduleRef.createNestApplication<NestExpressApplication>();
    app.useBodyParser('json', {
      verify: (req: RawBodyRequest, _res: unknown, buf: Buffer) => {
        req.rawBody = buf;
      },
    });
    app.useGlobalPipes(
      new ValidationPipe({
        whitelist: true,
        forbidNonWhitelisted: true,
        transform: true,
      }),
    );
    await app.init();
    server = app.getHttpServer() as Server;
  });

  afterAll(async () => {
    await app.close();
    delete process.env.CONFIRMATION_TTL_SECONDS;
  });

  it('creates request with custom TTL', async () => {
    const res = await request(server)
      .post('/v1/engage')
      .send({
        mobileNumber: '+201234567904',
        message: 'TTL test',
        language: 'en',
        channel: 'whatsapp_text',
        ttlSeconds: 3600,
      })
      .expect(201);

    const { requestId } = res.body as { requestId: string };

    const details = await request(server)
      .get(`/v1/engage/${requestId}`)
      .expect(200);

    expect(details.body.expiresAt).toBeTruthy();
  });

  it('returns 410 for expired confirmation on get', async () => {
    const res = await request(server)
      .post('/v1/engage')
      .send({
        mobileNumber: '+201234567905',
        message: 'Expiry test',
        language: 'en',
        channel: 'whatsapp_text',
      })
      .expect(201);

    const { requestId } = res.body as { requestId: string };

    // Wait for expiry (TTL is 1 second)
    await new Promise((resolve) => setTimeout(resolve, 1100));

    await request(server).get(`/v1/engage/${requestId}`).expect(410);
  });

  it('returns 410 when trying to set result on expired confirmation', async () => {
    const res = await request(server)
      .post('/v1/engage')
      .send({
        mobileNumber: '+201234567906',
        message: 'Expiry result test',
        language: 'en',
        channel: 'whatsapp_text',
      })
      .expect(201);

    const { requestId } = res.body as { requestId: string };
    const providerMessageId = 'wa-expired-123';

    // Set provider info first
    await request(server)
      .post('/webhooks/whatsapp')
      .send({
        entry: [
          {
            changes: [
              {
                value: {
                  statuses: [
                    {
                      id: providerMessageId,
                      biz_opaque_callback_data: requestId,
                    },
                  ],
                },
              },
            ],
          },
        ],
      })
      .expect(201);

    // Wait for expiry
    await new Promise((resolve) => setTimeout(resolve, 1100));

    // Try to confirm - webhook should handle gracefully
    await request(server)
      .post('/webhooks/whatsapp')
      .send({
        entry: [
          {
            changes: [
              {
                value: {
                  messages: [
                    {
                      context: { id: providerMessageId },
                      text: { body: 'yes' },
                    },
                  ],
                },
              },
            ],
          },
        ],
      })
      .expect(201);

    // Verify still expired
    await request(server).get(`/v1/engage/${requestId}`).expect(410);
  });
});

describe('Twilio WhatsApp webhooks (e2e)', () => {
  let app: NestExpressApplication;
  let server: Server;

  beforeAll(async () => {
    process.env.ENGAGE_STORE = 'memory';
    delete process.env.API_KEY;
    process.env.WHATSAPP_PROVIDER = 'twilio';
    process.env.TWILIO_ACCOUNT_SID = '';
    process.env.TWILIO_AUTH_TOKEN = '';
    process.env.TWILIO_WHATSAPP_FROM = '';
    process.env.TWILIO_VALIDATE_SIGNATURE = 'false';
    process.env.PG_BOSS_CONNECTION_STRING = '';
    process.env.DATABASE_URL = '';
    process.env.PG_BOSS_WORKER_ENABLED = 'false';

    const moduleRef = await Test.createTestingModule({
      imports: [AppModule],
    }).compile();

    app = moduleRef.createNestApplication<NestExpressApplication>();
    app.useBodyParser('json', {
      verify: (req: RawBodyRequest, _res: unknown, buf: Buffer) => {
        req.rawBody = buf;
      },
    });
    app.useBodyParser('urlencoded', { extended: true });
    app.useGlobalPipes(
      new ValidationPipe({
        whitelist: true,
        forbidNonWhitelisted: true,
        transform: true,
      }),
    );
    await app.init();
    server = app.getHttpServer() as Server;
  });

  afterAll(async () => {
    await app.close();
  });

  it('handles Twilio WhatsApp status webhook', async () => {
    const res = await request(server)
      .post('/v1/engage')
      .send({
        mobileNumber: '+201234567907',
        message: 'Twilio WA status test',
        language: 'en',
        channel: 'whatsapp_text',
      })
      .expect(201);

    const { requestId } = res.body as { requestId: string };

    await request(server)
      .post(`/webhooks/twilio/whatsapp/status?requestId=${requestId}`)
      .type('form')
      .send({
        MessageSid: 'SM-twilio-wa-123',
        MessageStatus: 'delivered',
      })
      .expect(201);

    const updated = await request(server)
      .get(`/v1/engage/${requestId}`)
      .expect(200);

    expect(updated.body.providerMessageId).toBe('SM-twilio-wa-123');
  });

  it('handles Twilio WhatsApp inbound webhook', async () => {
    const res = await request(server)
      .post('/v1/engage')
      .send({
        mobileNumber: '+201234567908',
        message: 'Twilio WA inbound test',
        language: 'en',
        channel: 'whatsapp_text',
      })
      .expect(201);

    const { requestId } = res.body as { requestId: string };

    await request(server)
      .post(`/webhooks/twilio/whatsapp/inbound?requestId=${requestId}`)
      .type('form')
      .send({
        Body: 'confirm',
      })
      .expect(201);

    const updated = await request(server)
      .get(`/v1/engage/${requestId}`)
      .expect(200);

    expect(updated.body.result).toBe('confirmed');
  });
});

describe('EngageController (e2e) auth', () => {
  let app: NestExpressApplication;
  let server: Server;

  beforeAll(async () => {
    process.env.ENGAGE_STORE = 'memory';
    process.env.API_KEY = 'test-key';
    process.env.WHATSAPP_PROVIDER = '';
    process.env.WHATSAPP_PHONE_NUMBER_ID = '';
    process.env.WHATSAPP_ACCESS_TOKEN = '';
    process.env.CALL_PROVIDER = '';
    process.env.TWILIO_ACCOUNT_SID = '';
    process.env.TWILIO_AUTH_TOKEN = '';
    process.env.TWILIO_WHATSAPP_FROM = '';
    process.env.TWILIO_CALL_FROM = '';
    process.env.PUBLIC_BASE_URL = '';
    process.env.SLACK_WEBHOOK_URL = '';
    process.env.AI_MESSAGE_PROVIDER = '';
    process.env.PG_BOSS_CONNECTION_STRING = '';
    process.env.DATABASE_URL = '';
    process.env.PG_BOSS_WORKER_ENABLED = 'false';

    const moduleRef = await Test.createTestingModule({
      imports: [AppModule],
    }).compile();

    app = moduleRef.createNestApplication<NestExpressApplication>();
    app.useBodyParser('json', {
      verify: (req: RawBodyRequest, _res: unknown, buf: Buffer) => {
        req.rawBody = buf;
      },
    });
    app.useGlobalPipes(
      new ValidationPipe({
        whitelist: true,
        forbidNonWhitelisted: true,
        transform: true,
      }),
    );
    await app.init();
    server = app.getHttpServer() as Server;
  });

  afterAll(async () => {
    await app.close();
    delete process.env.API_KEY;
  });

  it('health endpoint is public', async () => {
    await request(server).get('/health').expect(200);
  });

  it('rejects protected requests without api key', async () => {
    await request(server).get('/v1/engage/test-id').expect(401);
  });

  it('accepts protected requests with valid api key', async () => {
    await request(server)
      .get('/v1/engage/test-id')
      .set('x-api-key', 'test-key')
      .expect(404);
  });
});
