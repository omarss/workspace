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

 - [CreateNotificationChannelRequest](docs/CreateNotificationChannelRequest.md)
 - [CreateTenantRequest](docs/CreateTenantRequest.md)
 - [CreateUserRequest](docs/CreateUserRequest.md)
 - [CredentialsBundle](docs/CredentialsBundle.md)
 - [FieldError](docs/FieldError.md)
 - [Health](docs/Health.md)
 - [LinkSocialProviderRequest](docs/LinkSocialProviderRequest.md)
 - [LinkSocialProviderResponse](docs/LinkSocialProviderResponse.md)
 - [Notification](docs/Notification.md)
 - [NotificationChannel](docs/NotificationChannel.md)
 - [NotificationChannelListResponse](docs/NotificationChannelListResponse.md)
 - [NotificationChannelResponse](docs/NotificationChannelResponse.md)
 - [NotificationListResponse](docs/NotificationListResponse.md)
 - [NotificationResponse](docs/NotificationResponse.md)
 - [NotificationWorkflow](docs/NotificationWorkflow.md)
 - [NotificationWorkflowListResponse](docs/NotificationWorkflowListResponse.md)
 - [NotificationWorkflowResponse](docs/NotificationWorkflowResponse.md)
 - [Pagination](docs/Pagination.md)
 - [Problem](docs/Problem.md)
 - [RegisterNotificationWorkflowRequest](docs/RegisterNotificationWorkflowRequest.md)
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
 - [UpdateNotificationChannelRequest](docs/UpdateNotificationChannelRequest.md)
 - [UpdateNotificationWorkflowRequest](docs/UpdateNotificationWorkflowRequest.md)
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

