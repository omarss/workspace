# TenantsApi

All URIs are relative to *https://dev.example.saas.omarss.net*

|Method | HTTP request | Description|
|------------- | ------------- | -------------|
|[**createTenant**](#createtenant) | **POST** /v1/tenants | Create a tenant. Auto-creates a default Organization.|
|[**deleteTenant**](#deletetenant) | **DELETE** /v1/tenants/{tenant_id} | Soft-delete a tenant. Retention applies before physical purge.|
|[**getTenant**](#gettenant) | **GET** /v1/tenants/{tenant_id} | Fetch a tenant by id.|
|[**listTenants**](#listtenants) | **GET** /v1/tenants | List tenants visible to the caller\&#39;s Deployment.|
|[**updateTenant**](#updatetenant) | **PATCH** /v1/tenants/{tenant_id} | Update a tenant. Idempotent. ETag concurrency control required.|

# **createTenant**
> TenantResponse createTenant(createTenantRequest)

Idempotent. Replays with the same Idempotency-Key + body return the cached 201 response; with the same key + a different body return 422 idempotency-key-conflict (see AGENTS.md section 5.2). 

### Example

```typescript
import {
    TenantsApi,
    Configuration,
    CreateTenantRequest
} from '@omarss/saas-dataplane-sdk';

const configuration = new Configuration();
const apiInstance = new TenantsApi(configuration);

let idempotencyKey: string; //24-hour idempotency key (idem_<ulid>). (default to undefined)
let createTenantRequest: CreateTenantRequest; //

const { status, data } = await apiInstance.createTenant(
    idempotencyKey,
    createTenantRequest
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **createTenantRequest** | **CreateTenantRequest**|  | |
| **idempotencyKey** | [**string**] | 24-hour idempotency key (idem_&lt;ulid&gt;). | defaults to undefined|


### Return type

**TenantResponse**

### Authorization

[apiKeyAuth](../README.md#apiKeyAuth), [bearerAuth](../README.md#bearerAuth)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json, application/problem+json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
|**201** | Created |  * ETag -  <br>  * Location - URI of the created user. <br>  |
|**401** | Missing or invalid bearer token / API key. |  -  |
|**409** | Concurrent request with the same Idempotency-Key is still processing. |  -  |
|**422** | Idempotency-Key reused with a different body, OR validation failed. |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **deleteTenant**
> deleteTenant()

Soft-deletes the tenant; status flips to \"deleted\" and a retention window applies before any physical purge (purge endpoint lands in Phase 18). 

### Example

```typescript
import {
    TenantsApi,
    Configuration
} from '@omarss/saas-dataplane-sdk';

const configuration = new Configuration();
const apiInstance = new TenantsApi(configuration);

let ifMatch: string; //Weak ETag from a prior GET; rejects on mismatch with 412. (default to undefined)
let tenantId: string; // (default to undefined)

const { status, data } = await apiInstance.deleteTenant(
    ifMatch,
    tenantId
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **ifMatch** | [**string**] | Weak ETag from a prior GET; rejects on mismatch with 412. | defaults to undefined|
| **tenantId** | [**string**] |  | defaults to undefined|


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
|**204** | Soft-deleted. |  -  |
|**401** | Missing or invalid bearer token / API key. |  -  |
|**403** | Caller lacks permission for this resource. |  -  |
|**404** | Resource not found. |  -  |
|**412** | If-Match header missing or stale. |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **getTenant**
> TenantResponse getTenant()

Returns the tenant if the caller\'s tenant context matches the path id; 403 otherwise.

### Example

```typescript
import {
    TenantsApi,
    Configuration
} from '@omarss/saas-dataplane-sdk';

const configuration = new Configuration();
const apiInstance = new TenantsApi(configuration);

let tenantId: string; // (default to undefined)

const { status, data } = await apiInstance.getTenant(
    tenantId
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **tenantId** | [**string**] |  | defaults to undefined|


### Return type

**TenantResponse**

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

# **listTenants**
> TenantListResponse listTenants()

Returns the tenants the caller is authorised to see. In Phase 2 the Data Plane caller\'s token resolves to exactly one tenant, so the list contains one element. Operator impersonation across tenants lands in Phase 13. 

### Example

```typescript
import {
    TenantsApi,
    Configuration
} from '@omarss/saas-dataplane-sdk';

const configuration = new Configuration();
const apiInstance = new TenantsApi(configuration);

let limit: number; //Max items to return (default 25, max 200). (optional) (default to 25)
let cursor: string; //Opaque pagination cursor; obtained from a previous response. (optional) (default to undefined)
let sort: string; //Sort token. Default \"-created_at\". (optional) (default to '-created_at')

const { status, data } = await apiInstance.listTenants(
    limit,
    cursor,
    sort
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **limit** | [**number**] | Max items to return (default 25, max 200). | (optional) defaults to 25|
| **cursor** | [**string**] | Opaque pagination cursor; obtained from a previous response. | (optional) defaults to undefined|
| **sort** | [**string**] | Sort token. Default \&quot;-created_at\&quot;. | (optional) defaults to '-created_at'|


### Return type

**TenantListResponse**

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

# **updateTenant**
> TenantResponse updateTenant(updateTenantRequest)

PATCH requires the current Weak ETag in If-Match; a stale ETag returns 412. Idempotency-Key replays the cached response when the body hash matches. 

### Example

```typescript
import {
    TenantsApi,
    Configuration,
    UpdateTenantRequest
} from '@omarss/saas-dataplane-sdk';

const configuration = new Configuration();
const apiInstance = new TenantsApi(configuration);

let ifMatch: string; //Weak ETag from a prior GET; rejects on mismatch with 412. (default to undefined)
let idempotencyKey: string; //24-hour idempotency key (idem_<ulid>). (default to undefined)
let tenantId: string; // (default to undefined)
let updateTenantRequest: UpdateTenantRequest; //

const { status, data } = await apiInstance.updateTenant(
    ifMatch,
    idempotencyKey,
    tenantId,
    updateTenantRequest
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **updateTenantRequest** | **UpdateTenantRequest**|  | |
| **ifMatch** | [**string**] | Weak ETag from a prior GET; rejects on mismatch with 412. | defaults to undefined|
| **idempotencyKey** | [**string**] | 24-hour idempotency key (idem_&lt;ulid&gt;). | defaults to undefined|
| **tenantId** | [**string**] |  | defaults to undefined|


### Return type

**TenantResponse**

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

