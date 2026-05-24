// Handwritten workflow wrapper over the generated TenantsApi.
//
// The generated client mirrors the OpenAPI shapes faithfully — useful for
// completeness but verbose for the common workflows AGENTS.md section 21 calls
// out (create a tenant, list, update, soft-delete). This wrapper packages
// idempotency-key generation, optimistic-concurrency ETag round-tripping, and
// next-cursor iteration so consumers don't reinvent them.

import type { AxiosInstance } from "axios";
import { ulid } from "ulidx";

import type { Configuration } from "../configuration";
import { TenantsApi } from "../api/tenants-api";
import type {
  CreateTenantRequest,
  Tenant,
  TenantListResponse,
  UpdateTenantRequest,
} from "../models";

// idem returns an "idem_<ulid>" idempotency key in the platform's expected
// format. Callers may pass an explicit key for replay tests.
function idem(): string {
  return `idem_${ulid()}`;
}

/**
 * TenantsWorkflow encapsulates the high-level operations a Product Builder
 * cares about. It is a thin wrapper — never reinvent business logic in here.
 */
export class TenantsWorkflow {
  private readonly api: TenantsApi;

  constructor(config: Configuration, axios?: AxiosInstance) {
    this.api = new TenantsApi(config, undefined, axios);
  }

  /** Create a tenant; returns the new Tenant payload with its weak ETag. */
  async create(
    slug: string,
    name: string,
    metadata?: Record<string, string>,
    idempotencyKey: string = idem(),
  ): Promise<Tenant> {
    const body: CreateTenantRequest = { slug, name, metadata };
    const res = await this.api.createTenant(idempotencyKey, body);
    return res.data.data;
  }

  /** Fetch a tenant by id. */
  async get(tenantId: string): Promise<Tenant> {
    const res = await this.api.getTenant(tenantId);
    return res.data.data;
  }

  /** List the tenants visible to the caller. Single-tenant in Phase 2. */
  async list(opts: { limit?: number; cursor?: string; sort?: string } = {}): Promise<TenantListResponse> {
    const res = await this.api.listTenants(opts.limit, opts.cursor, opts.sort);
    return res.data;
  }

  /**
   * Update a tenant. The caller passes the ETag from a previous GET; the
   * platform rejects stale ETags with 412 Precondition Failed (the workflow
   * surface returns axios errors verbatim — wrap if you need typed errors).
   */
  async update(
    tenantId: string,
    etag: string,
    patch: UpdateTenantRequest,
    idempotencyKey: string = idem(),
  ): Promise<Tenant> {
    const res = await this.api.updateTenant(etag, idempotencyKey, tenantId, patch);
    return res.data.data;
  }

  /** Soft-delete a tenant. */
  async delete(tenantId: string, etag: string): Promise<void> {
    await this.api.deleteTenant(etag, tenantId);
  }
}
