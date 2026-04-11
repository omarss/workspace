import { Injectable, OnModuleDestroy } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { auth, Client } from 'cassandra-driver';
import type {
  ArrayOrObject,
  ClientOptions,
  QueryOptions,
  types,
} from 'cassandra-driver';

@Injectable()
export class CassandraService implements OnModuleDestroy {
  private readonly client: Client;
  private connectPromise?: Promise<void>;

  constructor(private readonly configService: ConfigService) {
    const rawContactPoints = this.configService.get<string>(
      'CASSANDRA_CONTACT_POINTS',
    );
    const parsedContactPoints = rawContactPoints
      ? rawContactPoints
          .split(',')
          .map((entry) => entry.trim())
          .filter(Boolean)
      : [];
    const contactPoints =
      parsedContactPoints.length > 0 ? parsedContactPoints : ['127.0.0.1'];

    const localDataCenter =
      this.configService.get<string>('CASSANDRA_DATACENTER') ?? 'datacenter1';
    const keyspace =
      this.configService.get<string>('CASSANDRA_KEYSPACE') ?? 'reach_me';

    const portValue = this.configService.get<string>('CASSANDRA_PORT');
    const port = portValue ? Number(portValue) : undefined;

    const username = this.configService.get<string>('CASSANDRA_USERNAME');
    const password = this.configService.get<string>('CASSANDRA_PASSWORD');

    const options: ClientOptions = {
      contactPoints,
      localDataCenter,
      keyspace,
    };

    if (port) {
      options.protocolOptions = { port };
    }

    if (username && password) {
      options.authProvider = new auth.PlainTextAuthProvider(username, password);
    }

    this.client = new Client(options);
  }

  async execute(
    query: string,
    params?: ArrayOrObject,
    options?: QueryOptions,
  ): Promise<types.ResultSet> {
    await this.ensureConnected();
    return this.client.execute(query, params, options);
  }

  async onModuleDestroy(): Promise<void> {
    if (this.connectPromise) {
      await this.client.shutdown();
    }
  }

  private async ensureConnected(): Promise<void> {
    this.connectPromise ??= this.client.connect().catch((error) => {
      this.connectPromise = undefined;
      throw error;
    });

    await this.connectPromise;
  }
}
