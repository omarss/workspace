import { Module } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { CassandraService } from '../database/cassandra.service';
import { EngageController } from './engage.controller';
import { ENGAGE_STORE } from './engage.store';
import { EngageService } from './engage.service';
import { EngageQueueService } from './queue/engage-queue.service';
import { CallbackService } from './providers/callback.service';
import { EngageDispatchService } from './providers/dispatch.service';
import { LlmConfirmationInterpreter } from './providers/llm-confirmation-interpreter';
import { MessageComposerService } from './providers/message-composer.service';
import { SlackFallbackService } from './providers/slack-fallback.service';
import { TranslationService } from './providers/translation.service';
import { VoiceScriptService } from './providers/voice-script.service';
import { TwilioCallProvider } from './providers/twilio/twilio-call.provider';
import { TwilioSmsProvider } from './providers/twilio/twilio-sms.provider';
import { TwilioWebhookController } from './providers/twilio/twilio.controller';
import { TwilioWhatsAppProvider } from './providers/twilio/twilio-whatsapp.provider';
import { MetaWhatsAppProvider } from './providers/whatsapp/meta-whatsapp.service';
import { WhatsAppWebhookController } from './providers/whatsapp/whatsapp.controller';
import { CassandraEngageStore } from './stores/cassandra-engage.store';
import { InMemoryEngageStore } from './stores/in-memory-engage.store';

const engageStoreProvider = {
  provide: ENGAGE_STORE,
  useFactory: (
    configService: ConfigService,
    memoryStore: InMemoryEngageStore,
    cassandraStore: CassandraEngageStore,
  ) => {
    const configured = configService.get<string>('ENGAGE_STORE');
    const resolved = configured?.toLowerCase();

    if (resolved) {
      return resolved === 'cassandra' ? cassandraStore : memoryStore;
    }

    const hasCassandraConfig = Boolean(
      configService.get<string>('CASSANDRA_CONTACT_POINTS'),
    );
    return hasCassandraConfig ? cassandraStore : memoryStore;
  },
  inject: [ConfigService, InMemoryEngageStore, CassandraEngageStore],
};

@Module({
  controllers: [EngageController, WhatsAppWebhookController, TwilioWebhookController],
  providers: [
    CassandraService,
    InMemoryEngageStore,
    CassandraEngageStore,
    engageStoreProvider,
    EngageService,
    EngageQueueService,
    EngageDispatchService,
    CallbackService,
    LlmConfirmationInterpreter,
    MessageComposerService,
    SlackFallbackService,
    TranslationService,
    VoiceScriptService,
    MetaWhatsAppProvider,
    TwilioWhatsAppProvider,
    TwilioCallProvider,
    TwilioSmsProvider,
  ],
})
export class EngageModule {}
