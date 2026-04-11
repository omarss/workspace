import {
  Injectable,
  Logger,
  NotFoundException,
  OnModuleDestroy,
  OnModuleInit,
} from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import type { Job, PgBoss, WorkOptions } from 'pg-boss';
import type { ConfirmationRequest } from '../types';
import { EngageDispatchService } from '../providers/dispatch.service';
import { EngageService } from '../engage.service';

interface DispatchJob {
  requestId: string;
}

@Injectable()
export class EngageQueueService implements OnModuleInit, OnModuleDestroy {
  private readonly logger = new Logger(EngageQueueService.name);
  private boss?: PgBoss;
  private enabled = false;
  private readonly queueName: string;
  private readonly retryLimit: number;
  private readonly retryDelaySeconds: number;
  private readonly retryBackoff: boolean;
  private readonly batchSize: number;
  private readonly pollingIntervalSeconds: number;
  private readonly workerEnabled: boolean;

  constructor(
    private readonly configService: ConfigService,
    private readonly engageService: EngageService,
    private readonly dispatchService: EngageDispatchService,
  ) {
    this.queueName =
      this.configService.get<string>('PG_BOSS_QUEUE_NAME') ?? 'engage-dispatch';
    this.retryLimit = this.readNumber('PG_BOSS_RETRY_LIMIT', 3);
    this.retryDelaySeconds = this.readNumber('PG_BOSS_RETRY_DELAY_SECONDS', 30);
    this.retryBackoff =
      this.configService.get<string>('PG_BOSS_RETRY_BACKOFF') === 'true';
    this.batchSize = this.readNumber('PG_BOSS_BATCH_SIZE', 5);
    this.pollingIntervalSeconds = this.readNumber(
      'PG_BOSS_POLL_INTERVAL_SECONDS',
      5,
    );
    this.workerEnabled =
      this.configService.get<string>('PG_BOSS_WORKER_ENABLED') !== 'false';
  }

  async onModuleInit(): Promise<void> {
    const connectionString = this.resolveConnectionString();
    if (!connectionString) {
      this.logger.log('PG Boss disabled (no connection string configured)');
      return;
    }

    const { PgBoss } = await import('pg-boss');
    this.boss = new PgBoss({ connectionString });
    this.boss.on('error', (error: Error) => {
      this.logger.error(`PG Boss error: ${error.message}`);
    });

    await this.boss.start();
    this.enabled = true;
    this.logger.log('PG Boss queue started');

    if (this.workerEnabled) {
      const options: WorkOptions = {
        batchSize: this.batchSize,
        pollingIntervalSeconds: this.pollingIntervalSeconds,
      };
      await this.boss.work<DispatchJob>(
        this.queueName,
        options,
        async (jobs: Job<DispatchJob>[]) => {
          for (const job of jobs) {
            await this.handleDispatchJob(job);
          }
        },
      );
      this.logger.log('PG Boss worker started');
    }
  }

  async onModuleDestroy(): Promise<void> {
    if (this.boss) {
      await this.boss.stop();
    }
  }

  async enqueue(request: ConfirmationRequest): Promise<void> {
    if (!this.enabled || !this.boss) {
      await this.dispatchService.dispatch(request);
      return;
    }

    try {
      await this.boss.send(this.queueName, { requestId: request.id }, {
        retryLimit: this.retryLimit,
        retryDelay: this.retryDelaySeconds,
        retryBackoff: this.retryBackoff,
      });
    } catch (error) {
      this.logger.error(
        `Queue enqueue failed, dispatching inline: ${(error as Error).message}`,
      );
      await this.dispatchService.dispatch(request);
    }
  }

  private async handleDispatchJob(job: Job<DispatchJob>): Promise<void> {
    const requestId = job.data?.requestId;
    if (!requestId) {
      this.logger.warn('Queue job missing requestId');
      return;
    }

    try {
      const request = await this.engageService.get(requestId);
      await this.dispatchService.dispatch(request, { throwOnFailure: true });
    } catch (error) {
      if (error instanceof NotFoundException) {
        this.logger.warn(`Queue request not found: ${requestId}`);
        return;
      }
      throw error;
    }
  }

  private resolveConnectionString(): string | null {
    const fromEnv =
      this.configService.get<string>('PG_BOSS_CONNECTION_STRING') ??
      this.configService.get<string>('DATABASE_URL');
    if (!fromEnv) {
      return null;
    }

    const trimmed = fromEnv.trim();
    return trimmed ? trimmed : null;
  }

  private readNumber(key: string, fallback: number): number {
    const raw = this.configService.get<string>(key);
    const parsed = raw ? Number(raw) : NaN;
    if (Number.isFinite(parsed) && parsed > 0) {
      return parsed;
    }
    return fallback;
  }
}
