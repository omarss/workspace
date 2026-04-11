import { Injectable } from '@nestjs/common';
import type { types } from 'cassandra-driver';
import { CassandraService } from '../../database/cassandra.service';
import type { EngageStore } from '../engage.store';
import type { ConfirmationRequest, ConfirmationResult } from '../types';

const TABLE_NAME = 'confirmation_requests';

const CREATE_TABLE_QUERY = `
  CREATE TABLE IF NOT EXISTS ${TABLE_NAME} (
    id text PRIMARY KEY,
    mobile_number text,
    message text,
    language text,
    channel text,
    confirmation_result text,
    provider text,
    provider_message_id text,
    callback_url text,
    expires_at timestamp,
    created_at timestamp,
    updated_at timestamp
  )
`;

const ADD_PROVIDER_COLUMNS = [
  `ALTER TABLE ${TABLE_NAME} ADD provider text`,
  `ALTER TABLE ${TABLE_NAME} ADD provider_message_id text`,
  `ALTER TABLE ${TABLE_NAME} ADD callback_url text`,
  `ALTER TABLE ${TABLE_NAME} ADD expires_at timestamp`,
];

const CREATE_PROVIDER_INDEX = `
  CREATE INDEX IF NOT EXISTS confirmation_requests_provider_message_id_idx
  ON ${TABLE_NAME} (provider_message_id)
`;

@Injectable()
export class CassandraEngageStore implements EngageStore {
  private schemaReady?: Promise<void>;

  constructor(private readonly cassandra: CassandraService) {}

  async create(request: ConfirmationRequest): Promise<ConfirmationRequest> {
    await this.ensureSchema();
    const query = `
      INSERT INTO ${TABLE_NAME} (
        id,
        mobile_number,
        message,
        language,
        channel,
        confirmation_result,
        provider,
        provider_message_id,
        callback_url,
        expires_at,
        created_at,
        updated_at
      )
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `;

    await this.cassandra.execute(
      query,
      [
        request.id,
        request.mobileNumber,
        request.message,
        request.language,
        request.channel,
        request.result,
        request.provider ?? null,
        request.providerMessageId ?? null,
        request.callbackUrl ?? null,
        request.expiresAt ? new Date(request.expiresAt) : null,
        new Date(request.createdAt),
        new Date(request.updatedAt),
      ],
      { prepare: true },
    );

    return request;
  }

  async get(requestId: string): Promise<ConfirmationRequest | null> {
    await this.ensureSchema();
    const query = `
      SELECT
        id,
        mobile_number,
        message,
        language,
        channel,
        confirmation_result,
        provider,
        provider_message_id,
        callback_url,
        expires_at,
        created_at,
        updated_at
      FROM ${TABLE_NAME}
      WHERE id = ?
    `;

    const result = await this.cassandra.execute(query, [requestId], {
      prepare: true,
    });

    const row = result.first();
    return row ? this.mapRow(row) : null;
  }

  async setResult(
    requestId: string,
    result: ConfirmationResult,
    updatedAt: string,
  ): Promise<ConfirmationRequest | null> {
    const existing = await this.get(requestId);
    if (!existing) {
      return null;
    }

    const query = `
      UPDATE ${TABLE_NAME}
      SET confirmation_result = ?, updated_at = ?
      WHERE id = ?
    `;

    await this.cassandra.execute(
      query,
      [result, new Date(updatedAt), requestId],
      { prepare: true },
    );

    return {
      ...existing,
      result,
      updatedAt,
    };
  }

  async setProviderInfo(
    requestId: string,
    provider: string,
    providerMessageId: string,
    updatedAt: string,
  ): Promise<ConfirmationRequest | null> {
    const existing = await this.get(requestId);
    if (!existing) {
      return null;
    }

    const query = `
      UPDATE ${TABLE_NAME}
      SET provider = ?, provider_message_id = ?, updated_at = ?
      WHERE id = ?
    `;

    await this.cassandra.execute(
      query,
      [provider, providerMessageId, new Date(updatedAt), requestId],
      { prepare: true },
    );

    return {
      ...existing,
      provider,
      providerMessageId,
      updatedAt,
    };
  }

  async getByProviderMessageId(
    providerMessageId: string,
  ): Promise<ConfirmationRequest | null> {
    await this.ensureSchema();
    const query = `
      SELECT
        id,
        mobile_number,
        message,
        language,
        channel,
        confirmation_result,
        provider,
        provider_message_id,
        callback_url,
        expires_at,
        created_at,
        updated_at
      FROM ${TABLE_NAME}
      WHERE provider_message_id = ?
      LIMIT 1
    `;

    const result = await this.cassandra.execute(query, [providerMessageId], {
      prepare: true,
    });

    const row = result.first();
    return row ? this.mapRow(row) : null;
  }

  private async ensureSchema(): Promise<void> {
    this.schemaReady ??= (async () => {
      await this.cassandra.execute(CREATE_TABLE_QUERY);
      for (const statement of ADD_PROVIDER_COLUMNS) {
        await this.tryExecute(statement);
      }
      await this.cassandra.execute(CREATE_PROVIDER_INDEX);
    })();
    await this.schemaReady;
  }

  private mapRow(row: types.Row): ConfirmationRequest {
    const createdAt = row.get('created_at') as Date;
    const updatedAt = row.get('updated_at') as Date;
    const expiresAt = row.get('expires_at') as Date | null;
    const provider = row.get('provider') as string | null;
    const providerMessageId = row.get('provider_message_id') as string | null;
    const callbackUrl = row.get('callback_url') as string | null;

    return {
      id: row.get('id') as string,
      mobileNumber: row.get('mobile_number') as string,
      message: row.get('message') as string,
      language: row.get('language') as ConfirmationRequest['language'],
      channel: row.get('channel') as ConfirmationRequest['channel'],
      result: row.get('confirmation_result') as ConfirmationRequest['result'],
      provider: provider ?? undefined,
      providerMessageId: providerMessageId ?? undefined,
      callbackUrl: callbackUrl ?? undefined,
      expiresAt: expiresAt?.toISOString(),
      createdAt: createdAt.toISOString(),
      updatedAt: updatedAt.toISOString(),
    };
  }

  private async tryExecute(query: string): Promise<void> {
    try {
      await this.cassandra.execute(query);
    } catch (error) {
      const message = (error as Error).message.toLowerCase();
      if (message.includes('already exists')) {
        return;
      }
      throw error;
    }
  }
}
