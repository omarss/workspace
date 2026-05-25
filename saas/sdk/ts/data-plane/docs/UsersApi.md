# UsersApi

All URIs are relative to *https://dev.example.saas.omarss.net*

|Method | HTTP request | Description|
|------------- | ------------- | -------------|
|[**createUser**](#createuser) | **POST** /v1/users | Create a platform user. Mirrors the row into Keycloak.|
|[**deleteUser**](#deleteuser) | **DELETE** /v1/users/{user_id} | Soft-delete a platform user. Disables the Keycloak user.|
|[**disableUser**](#disableuser) | **POST** /v1/users/{user_id}/disable | Disable a platform user. Emits user.disabled.|
|[**enableUser**](#enableuser) | **POST** /v1/users/{user_id}/enable | Enable a previously-disabled platform user.|
|[**getUser**](#getuser) | **GET** /v1/users/{user_id} | Fetch a platform user by id.|
|[**listUsers**](#listusers) | **GET** /v1/users | List users in the caller\&#39;s tenant.|
|[**triggerEmailVerify**](#triggeremailverify) | **POST** /v1/users/{user_id}/verify-email | Trigger an email-verification action via Keycloak.|
|[**triggerPasswordReset**](#triggerpasswordreset) | **POST** /v1/users/{user_id}/reset-password | Trigger a password-reset email via Keycloak.|
|[**updateUser**](#updateuser) | **PATCH** /v1/users/{user_id} | Update a platform user. ETag concurrency control required.|

# **createUser**
> UserResponse createUser(createUserRequest)

Idempotent. The platform creates a row + a Keycloak user in the shared `saas-data-local` realm (per-Deployment realm lands in Phase 12). Email is envelope-encrypted; an HMAC-SHA256 lookup hash backs the per-tenant uniqueness index. 

### Example

```typescript
import {
    UsersApi,
    Configuration,
    CreateUserRequest
} from '@omarss/saas-dataplane-sdk';

const configuration = new Configuration();
const apiInstance = new UsersApi(configuration);

let idempotencyKey: string; //24-hour idempotency key (idem_<ulid>). (default to undefined)
let createUserRequest: CreateUserRequest; //

const { status, data } = await apiInstance.createUser(
    idempotencyKey,
    createUserRequest
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **createUserRequest** | **CreateUserRequest**|  | |
| **idempotencyKey** | [**string**] | 24-hour idempotency key (idem_&lt;ulid&gt;). | defaults to undefined|


### Return type

**UserResponse**

### Authorization

[apiKeyAuth](../README.md#apiKeyAuth), [bearerAuth](../README.md#bearerAuth)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json, application/problem+json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
|**201** | Created |  * ETag -  <br>  * Location -  <br>  |
|**401** | Missing or invalid bearer token / API key. |  -  |
|**409** | Concurrent request with the same Idempotency-Key is still processing. |  -  |
|**422** | Idempotency-Key reused with a different body, OR validation failed. |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **deleteUser**
> deleteUser()


### Example

```typescript
import {
    UsersApi,
    Configuration
} from '@omarss/saas-dataplane-sdk';

const configuration = new Configuration();
const apiInstance = new UsersApi(configuration);

let ifMatch: string; //Weak ETag from a prior GET; rejects on mismatch with 412. (default to undefined)
let userId: string; // (default to undefined)

const { status, data } = await apiInstance.deleteUser(
    ifMatch,
    userId
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **ifMatch** | [**string**] | Weak ETag from a prior GET; rejects on mismatch with 412. | defaults to undefined|
| **userId** | [**string**] |  | defaults to undefined|


### Return type

void (empty response body)

### Authorization

[apiKeyAuth](../README.md#apiKeyAuth), [bearerAuth](../README.md#bearerAuth)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/problem+json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
|**204** | Soft-deleted (status&#x3D;deleted; Keycloak Enabled&#x3D;false). |  -  |
|**401** | Missing or invalid bearer token / API key. |  -  |
|**403** | Caller lacks permission for this resource. |  -  |
|**404** | Resource not found. |  -  |
|**412** | If-Match header missing or stale. |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **disableUser**
> UserResponse disableUser()


### Example

```typescript
import {
    UsersApi,
    Configuration
} from '@omarss/saas-dataplane-sdk';

const configuration = new Configuration();
const apiInstance = new UsersApi(configuration);

let idempotencyKey: string; //24-hour idempotency key (idem_<ulid>). (default to undefined)
let userId: string; // (default to undefined)

const { status, data } = await apiInstance.disableUser(
    idempotencyKey,
    userId
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **idempotencyKey** | [**string**] | 24-hour idempotency key (idem_&lt;ulid&gt;). | defaults to undefined|
| **userId** | [**string**] |  | defaults to undefined|


### Return type

**UserResponse**

### Authorization

[apiKeyAuth](../README.md#apiKeyAuth), [bearerAuth](../README.md#bearerAuth)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json, application/problem+json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
|**200** | OK |  -  |
|**401** | Missing or invalid bearer token / API key. |  -  |
|**403** | Caller lacks permission for this resource. |  -  |
|**404** | Resource not found. |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **enableUser**
> UserResponse enableUser()


### Example

```typescript
import {
    UsersApi,
    Configuration
} from '@omarss/saas-dataplane-sdk';

const configuration = new Configuration();
const apiInstance = new UsersApi(configuration);

let idempotencyKey: string; //24-hour idempotency key (idem_<ulid>). (default to undefined)
let userId: string; // (default to undefined)

const { status, data } = await apiInstance.enableUser(
    idempotencyKey,
    userId
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **idempotencyKey** | [**string**] | 24-hour idempotency key (idem_&lt;ulid&gt;). | defaults to undefined|
| **userId** | [**string**] |  | defaults to undefined|


### Return type

**UserResponse**

### Authorization

[apiKeyAuth](../README.md#apiKeyAuth), [bearerAuth](../README.md#bearerAuth)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json, application/problem+json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
|**200** | OK |  -  |
|**401** | Missing or invalid bearer token / API key. |  -  |
|**403** | Caller lacks permission for this resource. |  -  |
|**404** | Resource not found. |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **getUser**
> UserResponse getUser()


### Example

```typescript
import {
    UsersApi,
    Configuration
} from '@omarss/saas-dataplane-sdk';

const configuration = new Configuration();
const apiInstance = new UsersApi(configuration);

let userId: string; // (default to undefined)

const { status, data } = await apiInstance.getUser(
    userId
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **userId** | [**string**] |  | defaults to undefined|


### Return type

**UserResponse**

### Authorization

[apiKeyAuth](../README.md#apiKeyAuth), [bearerAuth](../README.md#bearerAuth)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json, application/problem+json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
|**200** | OK |  * ETag -  <br>  |
|**401** | Missing or invalid bearer token / API key. |  -  |
|**403** | Caller lacks permission for this resource. |  -  |
|**404** | Resource not found. |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **listUsers**
> UserListResponse listUsers()

Returns the platform users belonging to the caller\'s tenant. Email plaintext is returned (decrypted at the persistence boundary); the envelope columns stay on the server. Set the `email` query parameter to look up a single user by email (HMAC-prefix lookup; never sends plaintext to the DB). 

### Example

```typescript
import {
    UsersApi,
    Configuration
} from '@omarss/saas-dataplane-sdk';

const configuration = new Configuration();
const apiInstance = new UsersApi(configuration);

let limit: number; //Max items to return (default 25, max 200). (optional) (default to 25)
let cursor: string; //Opaque pagination cursor; obtained from a previous response. (optional) (default to undefined)
let sort: string; //Sort token. Default \"-created_at\". (optional) (default to '-created_at')
let email: string; //HMAC-prefix lookup; matches on email_lookup_hash. (optional) (default to undefined)

const { status, data } = await apiInstance.listUsers(
    limit,
    cursor,
    sort,
    email
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **limit** | [**number**] | Max items to return (default 25, max 200). | (optional) defaults to 25|
| **cursor** | [**string**] | Opaque pagination cursor; obtained from a previous response. | (optional) defaults to undefined|
| **sort** | [**string**] | Sort token. Default \&quot;-created_at\&quot;. | (optional) defaults to '-created_at'|
| **email** | [**string**] | HMAC-prefix lookup; matches on email_lookup_hash. | (optional) defaults to undefined|


### Return type

**UserListResponse**

### Authorization

[apiKeyAuth](../README.md#apiKeyAuth), [bearerAuth](../README.md#bearerAuth)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json, application/problem+json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
|**200** | OK |  -  |
|**401** | Missing or invalid bearer token / API key. |  -  |
|**410** | Cursor schema version is no longer supported. |  -  |
|**429** | Rate limit exceeded. |  * RateLimit-Limit -  <br>  * RateLimit-Remaining -  <br>  * RateLimit-Reset -  <br>  * Retry-After -  <br>  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **triggerEmailVerify**
> triggerEmailVerify()


### Example

```typescript
import {
    UsersApi,
    Configuration
} from '@omarss/saas-dataplane-sdk';

const configuration = new Configuration();
const apiInstance = new UsersApi(configuration);

let idempotencyKey: string; //24-hour idempotency key (idem_<ulid>). (default to undefined)
let userId: string; // (default to undefined)

const { status, data } = await apiInstance.triggerEmailVerify(
    idempotencyKey,
    userId
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **idempotencyKey** | [**string**] | 24-hour idempotency key (idem_&lt;ulid&gt;). | defaults to undefined|
| **userId** | [**string**] |  | defaults to undefined|


### Return type

void (empty response body)

### Authorization

[apiKeyAuth](../README.md#apiKeyAuth), [bearerAuth](../README.md#bearerAuth)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/problem+json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
|**202** | Verify-email action queued. |  -  |
|**401** | Missing or invalid bearer token / API key. |  -  |
|**403** | Caller lacks permission for this resource. |  -  |
|**404** | Resource not found. |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **triggerPasswordReset**
> triggerPasswordReset()

Phase 5 uses Keycloak\'s built-in SMTP (ExecuteActionsEmail with UPDATE_PASSWORD). Phase 6 swaps the transport to the Notifications module + Novu without changing this endpoint. 

### Example

```typescript
import {
    UsersApi,
    Configuration
} from '@omarss/saas-dataplane-sdk';

const configuration = new Configuration();
const apiInstance = new UsersApi(configuration);

let idempotencyKey: string; //24-hour idempotency key (idem_<ulid>). (default to undefined)
let userId: string; // (default to undefined)

const { status, data } = await apiInstance.triggerPasswordReset(
    idempotencyKey,
    userId
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **idempotencyKey** | [**string**] | 24-hour idempotency key (idem_&lt;ulid&gt;). | defaults to undefined|
| **userId** | [**string**] |  | defaults to undefined|


### Return type

void (empty response body)

### Authorization

[apiKeyAuth](../README.md#apiKeyAuth), [bearerAuth](../README.md#bearerAuth)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/problem+json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
|**202** | Reset email queued. |  -  |
|**401** | Missing or invalid bearer token / API key. |  -  |
|**403** | Caller lacks permission for this resource. |  -  |
|**404** | Resource not found. |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **updateUser**
> UserResponse updateUser(updateUserRequest)


### Example

```typescript
import {
    UsersApi,
    Configuration,
    UpdateUserRequest
} from '@omarss/saas-dataplane-sdk';

const configuration = new Configuration();
const apiInstance = new UsersApi(configuration);

let ifMatch: string; //Weak ETag from a prior GET; rejects on mismatch with 412. (default to undefined)
let idempotencyKey: string; //24-hour idempotency key (idem_<ulid>). (default to undefined)
let userId: string; // (default to undefined)
let updateUserRequest: UpdateUserRequest; //

const { status, data } = await apiInstance.updateUser(
    ifMatch,
    idempotencyKey,
    userId,
    updateUserRequest
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **updateUserRequest** | **UpdateUserRequest**|  | |
| **ifMatch** | [**string**] | Weak ETag from a prior GET; rejects on mismatch with 412. | defaults to undefined|
| **idempotencyKey** | [**string**] | 24-hour idempotency key (idem_&lt;ulid&gt;). | defaults to undefined|
| **userId** | [**string**] |  | defaults to undefined|


### Return type

**UserResponse**

### Authorization

[apiKeyAuth](../README.md#apiKeyAuth), [bearerAuth](../README.md#bearerAuth)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json, application/problem+json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
|**200** | OK |  * ETag -  <br>  |
|**401** | Missing or invalid bearer token / API key. |  -  |
|**403** | Caller lacks permission for this resource. |  -  |
|**404** | Resource not found. |  -  |
|**412** | If-Match header missing or stale. |  -  |
|**422** | Idempotency-Key reused with a different body, OR validation failed. |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

