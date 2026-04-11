import { Module } from '@nestjs/common';
import { ConfigModule, ConfigService } from '@nestjs/config';
import { APP_GUARD } from '@nestjs/core';
import { ThrottlerGuard, ThrottlerModule } from '@nestjs/throttler';
import { ApiKeyGuard } from './auth/api-key.guard';
import { HealthController } from './health/health.controller';
import { LlmModule } from './llm/llm.module';
import { EngageModule } from './engage/engage.module';

@Module({
  imports: [
    ConfigModule.forRoot({
      isGlobal: true,
    }),
    ThrottlerModule.forRootAsync({
      inject: [ConfigService],
      useFactory: (configService: ConfigService) => {
        const ttl = Number(configService.get('RATE_LIMIT_TTL_SECONDS'));
        const limit = Number(configService.get('RATE_LIMIT_MAX'));

        return [
          {
            ttl: Number.isFinite(ttl) && ttl > 0 ? ttl : 60,
            limit: Number.isFinite(limit) && limit > 0 ? limit : 60,
          },
        ];
      },
    }),
    LlmModule,
    EngageModule,
  ],
  controllers: [HealthController],
  providers: [
    {
      provide: APP_GUARD,
      useClass: ThrottlerGuard,
    },
    {
      provide: APP_GUARD,
      useClass: ApiKeyGuard,
    },
  ],
})
export class AppModule {}
