# ApiKeysApi

All URIs are relative to *https://dev.example.saas.omarss.net*

|Method | HTTP request | Description|
|------------- | ------------- | -------------|
|[**createAPIKey**](#createapikey) | **POST** /v1/tenants/{tenant_id}/api-keys | Mint a new API key. Plaintext returned ONCE.|
|[**deleteAPIKey**](#deleteapikey) | **DELETE** /v1/api-keys/{api_key_id} | Soft-revoke an API key (alias of revoke).|
|[**getAPIKey**](#getapikey) | **GET** /v1/api-keys/{api_key_id} | Fetch an API key by id (no plaintext).|
|[**listAPIKeys**](#listapikeys) | **GET** /v1/tenants/{tenant_id}/api-keys | List API keys for a tenant.|
|[**revokeAPIKey**](#revokeapikey) | **POST** /v1/api-keys/{api_key_id}/revoke | Immediately revoke an API key (no grace).|
|[**rotateAPIKey**](#rotateapikey) | **POST** /v1/api-keys/{api_key_id}/rotate | Rotate an API key with optional grace period.|
|[**updateAPIKey**](#updateapikey) | **PATCH** /v1/api-keys/{api_key_id} | Update name, scopes, ip_allowlist, rate_limit.|

# **createAPIKey**
> CreateAPIKeyResponse createAPIKey(createAPIKeyRequest)

Creates an API key under the named tenant. The response body carries the plaintext bearer in `secret` — this is the only time it is returned. Subsequent reads expose only the prefix. The `apikey.write` permission is required when the deployment has SAAS_RBAC_ENFORCE_DESTRUCTIVE=true (Phase 8 retrofit). 

### Example

```typescript
import {
    ApiKeysApi,
    Configuration,
    CreateAPIKeyRequest
} from '@omarss/saas-dataplane-sdk';

const configuration = new Configuration();
const apiInstance = new ApiKeysApi(configuration);

let idempotencyKey: string; //24-hour idempotency key (idem_<ulid>). (default to undefined)
let tenantId: string; // (default to undefined)
let createAPIKeyRequest: CreateAPIKeyRequest; //

const { status, data } = await apiInstance.createAPIKey(
    idempotencyKey,
    tenantId,
    createAPIKeyRequest
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **createAPIKeyRequest** | **CreateAPIKeyRequest**|  | |
| **idempotencyKey** | [**string**] | 24-hour idempotency key (idem_&lt;ulid&gt;). | defaults to undefined|
| **tenantId** | [**string**] |  | defaults to undefined|


### Return type

**CreateAPIKeyResponse**

### Authorization

[apiKeyAuth](../README.md#apiKeyAuth), [bearerAuth](../README.md#bearerAuth)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json, application/problem+json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
|**201** | Created. The plaintext secret is returned ONCE. |  * ETag -  <br>  * Location -  <br>  |
|**401** | Missing or invalid bearer token / API key. |  -  |
|**403** | Caller lacks permission for this resource. |  -  |
|**422** | Idempotency-Key reused with a different body, OR validation failed. |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **deleteAPIKey**
> deleteAPIKey()


### Example

```typescript
import {
    ApiKeysApi,
    Configuration
} from '@omarss/saas-dataplane-sdk';

const configuration = new Configuration();
const apiInstance = new ApiKeysApi(configuration);

let apiKeyId: string; // (default to undefined)

const { status, data } = await apiInstance.deleteAPIKey(
    apiKeyId
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **apiKeyId** | [**string**] |  | defaults to undefined|


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
|**204** | Revoked. |  -  |
|**401** | Missing or invalid bearer token / API key. |  -  |
|**403** | Caller lacks permission for this resource. |  -  |
|**404** | Resource not found. |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **getAPIKey**
> APIKeyResponse getAPIKey()


### Example

```typescript
import {
    ApiKeysApi,
    Configuration
} from '@omarss/saas-dataplane-sdk';

const configuration = new Configuration();
const apiInstance = new ApiKeysApi(configuration);

let apiKeyId: string; // (default to undefined)

const { status, data } = await apiInstance.getAPIKey(
    apiKeyId
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **apiKeyId** | [**string**] |  | defaults to undefined|


### Return type

**APIKeyResponse**

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

# **listAPIKeys**
> APIKeyListResponse listAPIKeys()


### Example

```typescript
import {
    ApiKeysApi,
    Configuration
} from '@omarss/saas-dataplane-sdk';

const configuration = new Configuration();
const apiInstance = new ApiKeysApi(configuration);

let tenantId: string; // (default to undefined)
let limit: number; //Max items to return (default 25, max 200). (optional) (default to 25)
let cursor: string; //Opaque pagination cursor; obtained from a previous response. (optional) (default to undefined)

const { status, data } = await apiInstance.listAPIKeys(
    tenantId,
    limit,
    cursor
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **tenantId** | [**string**] |  | defaults to undefined|
| **limit** | [**number**] | Max items to return (default 25, max 200). | (optional) defaults to 25|
| **cursor** | [**string**] | Opaque pagination cursor; obtained from a previous response. | (optional) defaults to undefined|


### Return type

**APIKeyListResponse**

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

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **revokeAPIKey**
> APIKeyResponse revokeAPIKey()


### Example

```typescript
import {
    ApiKeysApi,
    Configuration
} from '@omarss/saas-dataplane-sdk';

const configuration = new Configuration();
const apiInstance = new ApiKeysApi(configuration);

let idempotencyKey: string; //24-hour idempotency key (idem_<ulid>). (default to undefined)
let apiKeyId: string; // (default to undefined)

const { status, data } = await apiInstance.revokeAPIKey(
    idempotencyKey,
    apiKeyId
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **idempotencyKey** | [**string**] | 24-hour idempotency key (idem_&lt;ulid&gt;). | defaults to undefined|
| **apiKeyId** | [**string**] |  | defaults to undefined|


### Return type

**APIKeyResponse**

### Authorization

[apiKeyAuth](../README.md#apiKeyAuth), [bearerAuth](../README.md#bearerAuth)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json, application/problem+json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
|**200** | Revoked. |  -  |
|**401** | Missing or invalid bearer token / API key. |  -  |
|**403** | Caller lacks permission for this resource. |  -  |
|**404** | Resource not found. |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **rotateAPIKey**
> RotateAPIKeyResponse rotateAPIKey()

Mints a new plaintext secret for the same row id and demotes the previous secret into a predecessor PHC valid until `predecessor_expires_at`. Requires `apikey.write` when SAAS_RBAC_ENFORCE_DESTRUCTIVE=true. 

### Example

```typescript
import {
    ApiKeysApi,
    Configuration,
    RotateAPIKeyRequest
} from '@omarss/saas-dataplane-sdk';

const configuration = new Configuration();
const apiInstance = new ApiKeysApi(configuration);

let idempotencyKey: string; //24-hour idempotency key (idem_<ulid>). (default to undefined)
let apiKeyId: string; // (default to undefined)
let rotateAPIKeyRequest: RotateAPIKeyRequest; // (optional)

const { status, data } = await apiInstance.rotateAPIKey(
    idempotencyKey,
    apiKeyId,
    rotateAPIKeyRequest
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **rotateAPIKeyRequest** | **RotateAPIKeyRequest**|  | |
| **idempotencyKey** | [**string**] | 24-hour idempotency key (idem_&lt;ulid&gt;). | defaults to undefined|
| **apiKeyId** | [**string**] |  | defaults to undefined|


### Return type

**RotateAPIKeyResponse**

### Authorization

[apiKeyAuth](../README.md#apiKeyAuth), [bearerAuth](../README.md#bearerAuth)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json, application/problem+json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
|**200** | Rotated. New plaintext returned ONCE. |  * ETag -  <br>  |
|**401** | Missing or invalid bearer token / API key. |  -  |
|**403** | Caller lacks permission for this resource. |  -  |
|**404** | Resource not found. |  -  |
|**422** | Idempotency-Key reused with a different body, OR validation failed. |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **updateAPIKey**
> APIKeyResponse updateAPIKey(updateAPIKeyRequest)


### Example

```typescript
import {
    ApiKeysApi,
    Configuration,
    UpdateAPIKeyRequest
} from '@omarss/saas-dataplane-sdk';

const configuration = new Configuration();
const apiInstance = new ApiKeysApi(configuration);

let ifMatch: string; //Weak ETag from a prior GET; rejects on mismatch with 412. (default to undefined)
let idempotencyKey: string; //24-hour idempotency key (idem_<ulid>). (default to undefined)
let apiKeyId: string; // (default to undefined)
let updateAPIKeyRequest: UpdateAPIKeyRequest; //

const { status, data } = await apiInstance.updateAPIKey(
    ifMatch,
    idempotencyKey,
    apiKeyId,
    updateAPIKeyRequest
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **updateAPIKeyRequest** | **UpdateAPIKeyRequest**|  | |
| **ifMatch** | [**string**] | Weak ETag from a prior GET; rejects on mismatch with 412. | defaults to undefined|
| **idempotencyKey** | [**string**] | 24-hour idempotency key (idem_&lt;ulid&gt;). | defaults to undefined|
| **apiKeyId** | [**string**] |  | defaults to undefined|


### Return type

**APIKeyResponse**

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

