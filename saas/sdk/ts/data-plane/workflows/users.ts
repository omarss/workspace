// Handwritten workflow wrapper over the generated UsersApi + SocialProvidersApi.
//
// Phase 5 (Identity) ships the /v1/users + /v1/users/{user_id}/social-providers
// surface; the generated client mirrors the OpenAPI shapes faithfully but is
// verbose for common workflows (create + manage a platform user, drive the
// social-link redirect). This wrapper packages idempotency-key generation,
// optimistic-concurrency ETag round-tripping, and the link-flow URL surface
// so consumers don't reinvent them.

import type { AxiosInstance } from "axios";
import { ulid } from "ulidx";

import type { Configuration } from "../configuration";
import { UsersApi } from "../api/users-api";
import { SocialProvidersApi, UnlinkSocialProviderProviderEnum } from "../api/social-providers-api";
import type {
  CreateUserRequest,
  LinkSocialProviderRequest,
  LinkSocialProviderResponse,
  SocialProviderListResponse,
  UpdateUserRequest,
  User,
  UserListResponse,
} from "../models";

// idem returns an "idem_<ulid>" idempotency key in the platform's expected
// format. Callers may pass an explicit key for replay tests.
function idem(): string {
  return `idem_${ulid()}`;
}

/**
 * UsersWorkflow encapsulates the high-level operations a Product Builder
 * cares about for the Identity slice. Thin wrapper — never reinvent business
 * logic here.
 */
export class UsersWorkflow {
  private readonly users: UsersApi;
  private readonly social: SocialProvidersApi;

  constructor(config: Configuration, axios?: AxiosInstance) {
    this.users = new UsersApi(config, undefined, axios);
    this.social = new SocialProvidersApi(config, undefined, axios);
  }

  /** Create a platform user; mirrors into Keycloak and returns the new User. */
  async create(
    email: string,
    name?: string,
    sendVerificationEmail?: boolean,
    metadata?: Record<string, string>,
    idempotencyKey: string = idem(),
  ): Promise<User> {
    const body: CreateUserRequest = {
      email,
      name,
      send_verification_email: sendVerificationEmail,
      metadata,
    };
    const res = await this.users.createUser(idempotencyKey, body);
    return res.data.data;
  }

  /** Fetch a user by id. */
  async get(userId: string): Promise<User> {
    const res = await this.users.getUser(userId);
    return res.data.data;
  }

  /** List users in the caller's tenant. Optional email filter is an HMAC lookup. */
  async list(opts: { limit?: number; cursor?: string; sort?: string; email?: string } = {}): Promise<UserListResponse> {
    const res = await this.users.listUsers(opts.limit, opts.cursor, opts.sort, opts.email);
    return res.data;
  }

  /**
   * Update a user. Caller passes the ETag from a previous GET; the platform
   * rejects stale ETags with 412 Precondition Failed (the workflow surface
   * returns axios errors verbatim — wrap if you need typed errors).
   */
  async update(
    userId: string,
    etag: string,
    patch: UpdateUserRequest,
    idempotencyKey: string = idem(),
  ): Promise<User> {
    const res = await this.users.updateUser(etag, idempotencyKey, userId, patch);
    return res.data.data;
  }

  /** Disable a user; propagates to Keycloak. */
  async disable(userId: string, idempotencyKey: string = idem()): Promise<User> {
    const res = await this.users.disableUser(idempotencyKey, userId);
    return res.data.data;
  }

  /** Re-enable a previously disabled user. */
  async enable(userId: string, idempotencyKey: string = idem()): Promise<User> {
    const res = await this.users.enableUser(idempotencyKey, userId);
    return res.data.data;
  }

  /** Ask Keycloak to send a password-reset email. Returns 202; this resolves to void. */
  async resetPassword(userId: string, idempotencyKey: string = idem()): Promise<void> {
    await this.users.triggerPasswordReset(idempotencyKey, userId);
  }

  /** Ask Keycloak to send a VERIFY_EMAIL action. */
  async verifyEmail(userId: string, idempotencyKey: string = idem()): Promise<void> {
    await this.users.triggerEmailVerify(idempotencyKey, userId);
  }

  /** List the federated identities currently linked to a user. */
  async listSocialProviders(userId: string): Promise<SocialProviderListResponse> {
    const res = await this.social.listSocialProviders(userId);
    return res.data;
  }

  /**
   * Start a social-login link. Returns the LinkSocialProviderResponse —
   * the caller MUST redirect the user's browser to authorization_url for
   * Keycloak to complete the OAuth dance with the external IdP.
   */
  async linkSocialProvider(
    userId: string,
    body: LinkSocialProviderRequest,
    idempotencyKey: string = idem(),
  ): Promise<LinkSocialProviderResponse> {
    const res = await this.social.linkSocialProvider(idempotencyKey, userId, body);
    return res.data;
  }

  /** Detach a federated identity (no proof-of-possession needed). */
  async unlinkSocialProvider(
    userId: string,
    provider: UnlinkSocialProviderProviderEnum,
  ): Promise<void> {
    await this.social.unlinkSocialProvider(userId, provider);
  }
}
