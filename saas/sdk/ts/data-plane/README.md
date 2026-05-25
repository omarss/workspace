## @omarss/saas-dataplane-sdk@0.0.3

This generator creates TypeScript/JavaScript client that utilizes [axios](https://github.com/axios/axios). The generated Node module can be used in the following environments:

Environment
* Node.js
* Webpack
* Browserify

Language level
* ES5 - you must have a Promises/A+ library installed
* ES6

Module system
* CommonJS
* ES6 module system

It can be used in both TypeScript and JavaScript. In TypeScript, the definition will be automatically resolved via `package.json`. ([Reference](https://www.typescriptlang.org/docs/handbook/declaration-files/consumption.html))

### Building

To build and compile the typescript sources to javascript use:
```
npm install
npm run build
```

### Publishing

First build the package then run `npm publish`

### Consuming

navigate to the folder of your consuming project and run one of the following commands.

_published:_

```
npm install @omarss/saas-dataplane-sdk@0.0.3 --save
```

_unPublished (not recommended):_

```
npm install PATH_TO_GENERATED_PACKAGE --save
```

### Documentation for API Endpoints

All URIs are relative to *https://dev.example.saas.omarss.net*

Class | Method | HTTP request | Description
------------ | ------------- | ------------- | -------------
*ApiKeysApi* | [**createAPIKey**](docs/ApiKeysApi.md#createapikey) | **POST** /v1/tenants/{tenant_id}/api-keys | Mint a new API key. Plaintext returned ONCE.
*ApiKeysApi* | [**deleteAPIKey**](docs/ApiKeysApi.md#deleteapikey) | **DELETE** /v1/api-keys/{api_key_id} | Soft-revoke an API key (alias of revoke).
*ApiKeysApi* | [**getAPIKey**](docs/ApiKeysApi.md#getapikey) | **GET** /v1/api-keys/{api_key_id} | Fetch an API key by id (no plaintext).
*ApiKeysApi* | [**listAPIKeys**](docs/ApiKeysApi.md#listapikeys) | **GET** /v1/tenants/{tenant_id}/api-keys | List API keys for a tenant.
*ApiKeysApi* | [**revokeAPIKey**](docs/ApiKeysApi.md#revokeapikey) | **POST** /v1/api-keys/{api_key_id}/revoke | Immediately revoke an API key (no grace).
*ApiKeysApi* | [**rotateAPIKey**](docs/ApiKeysApi.md#rotateapikey) | **POST** /v1/api-keys/{api_key_id}/rotate | Rotate an API key with optional grace period.
*ApiKeysApi* | [**updateAPIKey**](docs/ApiKeysApi.md#updateapikey) | **PATCH** /v1/api-keys/{api_key_id} | Update name, scopes, ip_allowlist, rate_limit.
*AuditApi* | [**exportAuditEvents**](docs/AuditApi.md#exportauditevents) | **POST** /v1/audit-events/export | Export filtered audit events as JSON or CSV.
*AuditApi* | [**getAuditEvent**](docs/AuditApi.md#getauditevent) | **GET** /v1/audit-events/{audit_event_id} | Fetch a single audit event by id.
*AuditApi* | [**listAuditEvents**](docs/AuditApi.md#listauditevents) | **GET** /v1/tenants/{tenant_id}/audit-events | List audit events for a tenant.
*AuthorizationApi* | [**assignMemberRole**](docs/AuthorizationApi.md#assignmemberrole) | **POST** /v1/members/{member_id}/roles | Assign a role to a member.
*AuthorizationApi* | [**batchCheckAuthorization**](docs/AuthorizationApi.md#batchcheckauthorization) | **POST** /v1/authorization/batch-check | Evaluate many checks in one call (max 100).
*AuthorizationApi* | [**checkAuthorization**](docs/AuthorizationApi.md#checkauthorization) | **POST** /v1/authorization/check | Evaluate a single (member, permission, tenant) check.
*AuthorizationApi* | [**createRole**](docs/AuthorizationApi.md#createrole) | **POST** /v1/tenants/{tenant_id}/roles | Create a new role in a tenant.
*AuthorizationApi* | [**deleteRole**](docs/AuthorizationApi.md#deleterole) | **DELETE** /v1/roles/{role_id} | Delete a role. System roles refuse delete with 422.
*AuthorizationApi* | [**getRole**](docs/AuthorizationApi.md#getrole) | **GET** /v1/roles/{role_id} | Fetch a role by id.
*AuthorizationApi* | [**listMemberRoles**](docs/AuthorizationApi.md#listmemberroles) | **GET** /v1/members/{member_id}/roles | List roles assigned to a member.
*AuthorizationApi* | [**listPermissions**](docs/AuthorizationApi.md#listpermissions) | **GET** /v1/permissions | List the deployment-wide permission catalogue.
*AuthorizationApi* | [**listRoles**](docs/AuthorizationApi.md#listroles) | **GET** /v1/tenants/{tenant_id}/roles | List roles in a tenant.
*AuthorizationApi* | [**unassignMemberRole**](docs/AuthorizationApi.md#unassignmemberrole) | **DELETE** /v1/members/{member_id}/roles/{role_id} | Unassign a role from a member.
*AuthorizationApi* | [**updateRole**](docs/AuthorizationApi.md#updaterole) | **PATCH** /v1/roles/{role_id} | Update a role. Permissions slice is set-replace.
*InvitationsApi* | [**acceptInvitation**](docs/InvitationsApi.md#acceptinvitation) | **POST** /v1/invitations/{invitation_id}/accept | Accept a pending invitation. Creates the Member row.
*InvitationsApi* | [**createInvitation**](docs/InvitationsApi.md#createinvitation) | **POST** /v1/organizations/{organization_id}/invitations | Create an invitation. Email is queued; plaintext token returned ONCE.
*InvitationsApi* | [**getInvitation**](docs/InvitationsApi.md#getinvitation) | **GET** /v1/invitations/{invitation_id} | Fetch an invitation by id. Plaintext token never echoed.
*InvitationsApi* | [**listInvitations**](docs/InvitationsApi.md#listinvitations) | **GET** /v1/organizations/{organization_id}/invitations | List invitations for an organization.
*InvitationsApi* | [**revokeInvitation**](docs/InvitationsApi.md#revokeinvitation) | **DELETE** /v1/invitations/{invitation_id} | Revoke a pending invitation. Returns 204.
*MembersApi* | [**getMember**](docs/MembersApi.md#getmember) | **GET** /v1/organizations/{organization_id}/members/{member_id} | Fetch a member by id.
*MembersApi* | [**listMembers**](docs/MembersApi.md#listmembers) | **GET** /v1/organizations/{organization_id}/members | List members of an organization.
*MembersApi* | [**removeMember**](docs/MembersApi.md#removemember) | **DELETE** /v1/organizations/{organization_id}/members/{member_id} | Remove a member (soft-delete; status&#x3D;\&#39;removed\&#39;).
*MembersApi* | [**updateMember**](docs/MembersApi.md#updatemember) | **PATCH** /v1/organizations/{organization_id}/members/{member_id} | Update a member\&#39;s role assignment (Phase 8 RBAC placeholder).
*MetaApi* | [**getHealthz**](docs/MetaApi.md#gethealthz) | **GET** /healthz | Liveness probe.
*NotificationChannelsApi* | [**createNotificationChannel**](docs/NotificationChannelsApi.md#createnotificationchannel) | **POST** /v1/notification-channels | Create a BYOK notification channel.
*NotificationChannelsApi* | [**deleteNotificationChannel**](docs/NotificationChannelsApi.md#deletenotificationchannel) | **DELETE** /v1/notification-channels/{channel_id} | Soft-delete a notification channel.
*NotificationChannelsApi* | [**getNotificationChannel**](docs/NotificationChannelsApi.md#getnotificationchannel) | **GET** /v1/notification-channels/{channel_id} | Fetch a notification channel by id.
*NotificationChannelsApi* | [**listNotificationChannels**](docs/NotificationChannelsApi.md#listnotificationchannels) | **GET** /v1/notification-channels | List BYOK notification channels in the caller\&#39;s tenant.
*NotificationChannelsApi* | [**rotateNotificationChannelCredentials**](docs/NotificationChannelsApi.md#rotatenotificationchannelcredentials) | **POST** /v1/notification-channels/{channel_id}/rotate-credentials | Rotate a channel\&#39;s BYOK credentials.
*NotificationChannelsApi* | [**updateNotificationChannel**](docs/NotificationChannelsApi.md#updatenotificationchannel) | **PATCH** /v1/notification-channels/{channel_id} | Update a notification channel (metadata only).
*NotificationWorkflowsApi* | [**listNotificationWorkflows**](docs/NotificationWorkflowsApi.md#listnotificationworkflows) | **GET** /v1/notification-workflows | List registered notification workflows for the caller\&#39;s tenant.
*NotificationWorkflowsApi* | [**registerNotificationWorkflow**](docs/NotificationWorkflowsApi.md#registernotificationworkflow) | **POST** /v1/notification-workflows | Register a (name → Novu workflow id) mapping.
*NotificationWorkflowsApi* | [**updateNotificationWorkflow**](docs/NotificationWorkflowsApi.md#updatenotificationworkflow) | **PATCH** /v1/notification-workflows/{workflow_id} | Update the Novu workflow id and/or description for a registered workflow.
*NotificationsApi* | [**getNotification**](docs/NotificationsApi.md#getnotification) | **GET** /v1/notifications/{notification_id} | Fetch a notification by id.
*NotificationsApi* | [**listNotifications**](docs/NotificationsApi.md#listnotifications) | **GET** /v1/notifications | List notifications in the caller\&#39;s tenant.
*NotificationsApi* | [**sendNotification**](docs/NotificationsApi.md#sendnotification) | **POST** /v1/notifications/send | Queue a notification for delivery via Novu.
*OrganizationsApi* | [**createOrganization**](docs/OrganizationsApi.md#createorganization) | **POST** /v1/tenants/{tenant_id}/organizations | Create a new organization in a tenant (multi_org required).
*OrganizationsApi* | [**deleteOrganization**](docs/OrganizationsApi.md#deleteorganization) | **DELETE** /v1/organizations/{organization_id} | Soft-delete an organization. Refuses while active members remain.
*OrganizationsApi* | [**getOrganization**](docs/OrganizationsApi.md#getorganization) | **GET** /v1/organizations/{organization_id} | Fetch an organization by id.
*OrganizationsApi* | [**listOrganizations**](docs/OrganizationsApi.md#listorganizations) | **GET** /v1/tenants/{tenant_id}/organizations | List organizations in a tenant.
*OrganizationsApi* | [**updateOrganization**](docs/OrganizationsApi.md#updateorganization) | **PATCH** /v1/organizations/{organization_id} | Update an organization.
*SocialProvidersApi* | [**linkSocialProvider**](docs/SocialProvidersApi.md#linksocialprovider) | **POST** /v1/users/{user_id}/social-providers | Start a social-provider link flow. Returns the Keycloak link URL.
*SocialProvidersApi* | [**listSocialProviders**](docs/SocialProvidersApi.md#listsocialproviders) | **GET** /v1/users/{user_id}/social-providers | List linked social providers for a user.
*SocialProvidersApi* | [**unlinkSocialProvider**](docs/SocialProvidersApi.md#unlinksocialprovider) | **DELETE** /v1/users/{user_id}/social-providers/{provider} | Unlink a social provider. Emits user.social_unlinked.
*TenantsApi* | [**createTenant**](docs/TenantsApi.md#createtenant) | **POST** /v1/tenants | Create a tenant. Auto-creates a default Organization.
*TenantsApi* | [**deleteTenant**](docs/TenantsApi.md#deletetenant) | **DELETE** /v1/tenants/{tenant_id} | Soft-delete a tenant. Retention applies before physical purge.
*TenantsApi* | [**getTenant**](docs/TenantsApi.md#gettenant) | **GET** /v1/tenants/{tenant_id} | Fetch a tenant by id.
*TenantsApi* | [**listTenants**](docs/TenantsApi.md#listtenants) | **GET** /v1/tenants | List tenants visible to the caller\&#39;s Deployment.
*TenantsApi* | [**updateTenant**](docs/TenantsApi.md#updatetenant) | **PATCH** /v1/tenants/{tenant_id} | Update a tenant. Idempotent. ETag concurrency control required.
*UsersApi* | [**createUser**](docs/UsersApi.md#createuser) | **POST** /v1/users | Create a platform user. Mirrors the row into Keycloak.
*UsersApi* | [**deleteUser**](docs/UsersApi.md#deleteuser) | **DELETE** /v1/users/{user_id} | Soft-delete a platform user. Disables the Keycloak user.
*UsersApi* | [**disableUser**](docs/UsersApi.md#disableuser) | **POST** /v1/users/{user_id}/disable | Disable a platform user. Emits user.disabled.
*UsersApi* | [**enableUser**](docs/UsersApi.md#enableuser) | **POST** /v1/users/{user_id}/enable | Enable a previously-disabled platform user.
*UsersApi* | [**getUser**](docs/UsersApi.md#getuser) | **GET** /v1/users/{user_id} | Fetch a platform user by id.
*UsersApi* | [**listUsers**](docs/UsersApi.md#listusers) | **GET** /v1/users | List users in the caller\&#39;s tenant.
*UsersApi* | [**triggerEmailVerify**](docs/UsersApi.md#triggeremailverify) | **POST** /v1/users/{user_id}/verify-email | Trigger an email-verification action via Keycloak.
*UsersApi* | [**triggerPasswordReset**](docs/UsersApi.md#triggerpasswordreset) | **POST** /v1/users/{user_id}/reset-password | Trigger a password-reset email via Keycloak.
*UsersApi* | [**updateUser**](docs/UsersApi.md#updateuser) | **PATCH** /v1/users/{user_id} | Update a platform user. ETag concurrency control required.


### Documentation For Models

 - [APIKey](docs/APIKey.md)
 - [APIKeyListResponse](docs/APIKeyListResponse.md)
 - [APIKeyResponse](docs/APIKeyResponse.md)
 - [AcceptInvitationRequest](docs/AcceptInvitationRequest.md)
 - [AssignMemberRoleRequest](docs/AssignMemberRoleRequest.md)
 - [AuditEvent](docs/AuditEvent.md)
 - [AuditEventListResponse](docs/AuditEventListResponse.md)
 - [AuditEventResponse](docs/AuditEventResponse.md)
 - [BatchCheckAuthorizationRequest](docs/BatchCheckAuthorizationRequest.md)
 - [BatchCheckAuthorizationResponse](docs/BatchCheckAuthorizationResponse.md)
 - [CheckAuthorizationRequest](docs/CheckAuthorizationRequest.md)
 - [CheckAuthorizationResponse](docs/CheckAuthorizationResponse.md)
 - [CheckAuthorizationResponseData](docs/CheckAuthorizationResponseData.md)
 - [CreateAPIKeyRequest](docs/CreateAPIKeyRequest.md)
 - [CreateAPIKeyResponse](docs/CreateAPIKeyResponse.md)
 - [CreateInvitationRequest](docs/CreateInvitationRequest.md)
 - [CreateInvitationResponse](docs/CreateInvitationResponse.md)
 - [CreateNotificationChannelRequest](docs/CreateNotificationChannelRequest.md)
 - [CreateOrganizationRequest](docs/CreateOrganizationRequest.md)
 - [CreateRoleRequest](docs/CreateRoleRequest.md)
 - [CreateTenantRequest](docs/CreateTenantRequest.md)
 - [CreateUserRequest](docs/CreateUserRequest.md)
 - [CredentialsBundle](docs/CredentialsBundle.md)
 - [ExportAuditEventsRequest](docs/ExportAuditEventsRequest.md)
 - [FieldError](docs/FieldError.md)
 - [Health](docs/Health.md)
 - [Invitation](docs/Invitation.md)
 - [InvitationListResponse](docs/InvitationListResponse.md)
 - [InvitationResponse](docs/InvitationResponse.md)
 - [LinkSocialProviderRequest](docs/LinkSocialProviderRequest.md)
 - [LinkSocialProviderResponse](docs/LinkSocialProviderResponse.md)
 - [Member](docs/Member.md)
 - [MemberListResponse](docs/MemberListResponse.md)
 - [MemberResponse](docs/MemberResponse.md)
 - [MemberRoleAssignment](docs/MemberRoleAssignment.md)
 - [MemberRoleListResponse](docs/MemberRoleListResponse.md)
 - [MemberRoleResponse](docs/MemberRoleResponse.md)
 - [Notification](docs/Notification.md)
 - [NotificationChannel](docs/NotificationChannel.md)
 - [NotificationChannelListResponse](docs/NotificationChannelListResponse.md)
 - [NotificationChannelResponse](docs/NotificationChannelResponse.md)
 - [NotificationListResponse](docs/NotificationListResponse.md)
 - [NotificationResponse](docs/NotificationResponse.md)
 - [NotificationWorkflow](docs/NotificationWorkflow.md)
 - [NotificationWorkflowListResponse](docs/NotificationWorkflowListResponse.md)
 - [NotificationWorkflowResponse](docs/NotificationWorkflowResponse.md)
 - [Organization](docs/Organization.md)
 - [OrganizationListResponse](docs/OrganizationListResponse.md)
 - [OrganizationResponse](docs/OrganizationResponse.md)
 - [Pagination](docs/Pagination.md)
 - [Permission](docs/Permission.md)
 - [PermissionListResponse](docs/PermissionListResponse.md)
 - [Problem](docs/Problem.md)
 - [RegisterNotificationWorkflowRequest](docs/RegisterNotificationWorkflowRequest.md)
 - [Role](docs/Role.md)
 - [RoleListResponse](docs/RoleListResponse.md)
 - [RoleResponse](docs/RoleResponse.md)
 - [RotateAPIKeyRequest](docs/RotateAPIKeyRequest.md)
 - [RotateAPIKeyResponse](docs/RotateAPIKeyResponse.md)
 - [RotateChannelCredentialsRequest](docs/RotateChannelCredentialsRequest.md)
 - [SESCredentials](docs/SESCredentials.md)
 - [SMTPCredentials](docs/SMTPCredentials.md)
 - [SendGridCredentials](docs/SendGridCredentials.md)
 - [SendNotificationRequest](docs/SendNotificationRequest.md)
 - [SendNotificationRequestTo](docs/SendNotificationRequestTo.md)
 - [SocialProvider](docs/SocialProvider.md)
 - [SocialProviderListResponse](docs/SocialProviderListResponse.md)
 - [Tenant](docs/Tenant.md)
 - [TenantListResponse](docs/TenantListResponse.md)
 - [TenantResponse](docs/TenantResponse.md)
 - [UpdateAPIKeyRequest](docs/UpdateAPIKeyRequest.md)
 - [UpdateMemberRequest](docs/UpdateMemberRequest.md)
 - [UpdateNotificationChannelRequest](docs/UpdateNotificationChannelRequest.md)
 - [UpdateNotificationWorkflowRequest](docs/UpdateNotificationWorkflowRequest.md)
 - [UpdateOrganizationRequest](docs/UpdateOrganizationRequest.md)
 - [UpdateRoleRequest](docs/UpdateRoleRequest.md)
 - [UpdateTenantRequest](docs/UpdateTenantRequest.md)
 - [UpdateUserRequest](docs/UpdateUserRequest.md)
 - [User](docs/User.md)
 - [UserListResponse](docs/UserListResponse.md)
 - [UserResponse](docs/UserResponse.md)


<a id="documentation-for-authorization"></a>
## Documentation For Authorization


Authentication schemes defined for the API:
<a id="bearerAuth"></a>
### bearerAuth

- **Type**: Bearer authentication (JWT)

<a id="apiKeyAuth"></a>
### apiKeyAuth

- **Type**: Bearer authentication (API key)

