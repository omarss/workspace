import { afterAll, beforeAll, describe, expect, it } from 'bun:test';
import { Test, type TestingModule } from '@nestjs/testing';
import { ConfigModule } from '@nestjs/config';
import { auth, Client } from 'cassandra-driver';
import type { ClientOptions } from 'cassandra-driver';
import { randomUUID } from 'node:crypto';
import { CassandraService } from '../src/database/cassandra.service';
import { CassandraEngageStore } from '../src/engage/stores/cassandra-engage.store';
import { Channel, ConfirmationResult, Language } from '../src/engage/types';

const enabled = process.env.CASSANDRA_TEST_ENABLED === 'true';
const describeIf = enabled ? describe : describe.skip;

function parseContactPoints(): string[] {
  const raw = process.env.CASSANDRA_CONTACT_POINTS ?? '127.0.0.1';
  return raw
    .split(',')
    .map((entry) => entry.trim())
    .filter(Boolean);
}

async function ensureKeyspace(keyspace: string): Promise<void> {
  if (!/^[a-zA-Z0-9_]+$/.test(keyspace)) {
    throw new Error(`Invalid keyspace name: ${keyspace}`);
  }

  const options: ClientOptions = {
    contactPoints: parseContactPoints(),
    localDataCenter: process.env.CASSANDRA_DATACENTER ?? 'datacenter1',
  };

  const portValue = process.env.CASSANDRA_PORT;
  if (portValue) {
    const port = Number(portValue);
    if (Number.isFinite(port) && port > 0) {
      options.protocolOptions = { port };
    }
  }

  const username = process.env.CASSANDRA_USERNAME;
  const password = process.env.CASSANDRA_PASSWORD;
  if (username && password) {
    options.authProvider = new auth.PlainTextAuthProvider(username, password);
  }

  const client = new Client(options);
  await client.connect();
  await client.execute(
    `CREATE KEYSPACE IF NOT EXISTS ${keyspace} WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 1};`,
  );
  await client.shutdown();
}

describeIf('CassandraEngageStore', () => {
  let store: CassandraEngageStore;
  let cassandra: CassandraService;
  let cleanupIds: string[] = [];
  let moduleRef: TestingModule;
  let originalKeyspace: string | undefined;

  beforeAll(async () => {
    originalKeyspace = process.env.CASSANDRA_KEYSPACE;
    const keyspace = originalKeyspace ?? 'reach_me_test';
    process.env.CASSANDRA_KEYSPACE = keyspace;

    await ensureKeyspace(keyspace);

    moduleRef = await Test.createTestingModule({
      imports: [ConfigModule.forRoot({ isGlobal: true })],
      providers: [CassandraService, CassandraEngageStore],
    }).compile();

    store = moduleRef.get(CassandraEngageStore);
    cassandra = moduleRef.get(CassandraService);
  });

  afterAll(async () => {
    for (const id of cleanupIds) {
      try {
        await cassandra.execute(
          'DELETE FROM confirmation_requests WHERE id = ?',
          [id],
          { prepare: true },
        );
      } catch {
        // Best-effort cleanup for test data.
      }
    }

    if (moduleRef) {
      await moduleRef.close();
    }

    if (originalKeyspace === undefined) {
      delete process.env.CASSANDRA_KEYSPACE;
    } else {
      process.env.CASSANDRA_KEYSPACE = originalKeyspace;
    }
  });

  it('creates and reads a request', async () => {
    const now = new Date().toISOString();
    const requestId = randomUUID();

    await store.create({
      id: requestId,
      mobileNumber: '+201234567890',
      message: 'hello cassandra',
      language: Language.EN,
      channel: Channel.WHATSAPP_TEXT,
      result: ConfirmationResult.NOT_CONFIRMED,
      createdAt: now,
      updatedAt: now,
    });
    cleanupIds.push(requestId);

    const loaded = await store.get(requestId);
    expect(loaded?.id).toBe(requestId);
    expect(loaded?.message).toBe('hello cassandra');
  });

  it('updates result and provider info', async () => {
    const now = new Date().toISOString();
    const requestId = randomUUID();

    await store.create({
      id: requestId,
      mobileNumber: '+201234567891',
      message: 'provider mapping',
      language: Language.EN,
      channel: Channel.WHATSAPP_TEXT,
      result: ConfirmationResult.NOT_CONFIRMED,
      createdAt: now,
      updatedAt: now,
    });
    cleanupIds.push(requestId);

    const updated = await store.setResult(
      requestId,
      ConfirmationResult.CONFIRMED,
      new Date().toISOString(),
    );
    expect(updated?.result).toBe(ConfirmationResult.CONFIRMED);

    const providerId = `provider-${randomUUID()}`;
    await store.setProviderInfo(
      requestId,
      'meta_whatsapp',
      providerId,
      new Date().toISOString(),
    );

    const byProvider = await store.getByProviderMessageId(providerId);
    expect(byProvider?.id).toBe(requestId);
    expect(byProvider?.providerMessageId).toBe(providerId);
  });
});
