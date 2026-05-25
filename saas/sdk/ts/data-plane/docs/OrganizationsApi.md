# OrganizationsApi

All URIs are relative to *https://dev.example.saas.omarss.net*

|Method | HTTP request | Description|
|------------- | ------------- | -------------|
|[**createOrganization**](#createorganization) | **POST** /v1/tenants/{tenant_id}/organizations | Create a new organization in a tenant (multi_org required).|
|[**deleteOrganization**](#deleteorganization) | **DELETE** /v1/organizations/{organization_id} | Soft-delete an organization. Refuses while active members remain.|
|[**getOrganization**](#getorganization) | **GET** /v1/organizations/{organization_id} | Fetch an organization by id.|
|[**listOrganizations**](#listorganizations) | **GET** /v1/tenants/{tenant_id}/organizations | List organizations in a tenant.|
|[**updateOrganization**](#updateorganization) | **PATCH** /v1/organizations/{organization_id} | Update an organization.|

# **createOrganization**
> OrganizationResponse createOrganization(createOrganizationRequest)

Creating extra organizations requires `tenant.metadata.multi_org=true`. The default organization is auto-created on tenant.create and cannot be created via this endpoint. 

### Example

```typescript
import {
    OrganizationsApi,
    Configuration,
    CreateOrganizationRequest
} from '@omarss/saas-dataplane-sdk';

const configuration = new Configuration();
const apiInstance = new OrganizationsApi(configuration);

let idempotencyKey: string; //24-hour idempotency key (idem_<ulid>). (default to undefined)
let tenantId: string; // (default to undefined)
let createOrganizationRequest: CreateOrganizationRequest; //

const { status, data } = await apiInstance.createOrganization(
    idempotencyKey,
    tenantId,
    createOrganizationRequest
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **createOrganizationRequest** | **CreateOrganizationRequest**|  | |
| **idempotencyKey** | [**string**] | 24-hour idempotency key (idem_&lt;ulid&gt;). | defaults to undefined|
| **tenantId** | [**string**] |  | defaults to undefined|


### Return type

**OrganizationResponse**

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
|**403** | Caller lacks permission for this resource. |  -  |
|**405** | Multi-org is disabled for this tenant. |  -  |
|**409** | Concurrent request with the same Idempotency-Key is still processing. |  -  |
|**422** | Idempotency-Key reused with a different body, OR validation failed. |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **deleteOrganization**
> deleteOrganization()


### Example

```typescript
import {
    OrganizationsApi,
    Configuration
} from '@omarss/saas-dataplane-sdk';

const configuration = new Configuration();
const apiInstance = new OrganizationsApi(configuration);

let ifMatch: string; //Weak ETag from a prior GET; rejects on mismatch with 412. (default to undefined)
let organizationId: string; // (default to undefined)

const { status, data } = await apiInstance.deleteOrganization(
    ifMatch,
    organizationId
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **ifMatch** | [**string**] | Weak ETag from a prior GET; rejects on mismatch with 412. | defaults to undefined|
| **organizationId** | [**string**] |  | defaults to undefined|


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
|**422** | Idempotency-Key reused with a different body, OR validation failed. |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **getOrganization**
> OrganizationResponse getOrganization()


### Example

```typescript
import {
    OrganizationsApi,
    Configuration
} from '@omarss/saas-dataplane-sdk';

const configuration = new Configuration();
const apiInstance = new OrganizationsApi(configuration);

let organizationId: string; // (default to undefined)

const { status, data } = await apiInstance.getOrganization(
    organizationId
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **organizationId** | [**string**] |  | defaults to undefined|


### Return type

**OrganizationResponse**

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

# **listOrganizations**
> OrganizationListResponse listOrganizations()


### Example

```typescript
import {
    OrganizationsApi,
    Configuration
} from '@omarss/saas-dataplane-sdk';

const configuration = new Configuration();
const apiInstance = new OrganizationsApi(configuration);

let tenantId: string; // (default to undefined)
let limit: number; //Max items to return (default 25, max 200). (optional) (default to 25)
let cursor: string; //Opaque pagination cursor; obtained from a previous response. (optional) (default to undefined)

const { status, data } = await apiInstance.listOrganizations(
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

**OrganizationListResponse**

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
|**410** | Cursor schema version is no longer supported. |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **updateOrganization**
> OrganizationResponse updateOrganization(updateOrganizationRequest)


### Example

```typescript
import {
    OrganizationsApi,
    Configuration,
    UpdateOrganizationRequest
} from '@omarss/saas-dataplane-sdk';

const configuration = new Configuration();
const apiInstance = new OrganizationsApi(configuration);

let ifMatch: string; //Weak ETag from a prior GET; rejects on mismatch with 412. (default to undefined)
let idempotencyKey: string; //24-hour idempotency key (idem_<ulid>). (default to undefined)
let organizationId: string; // (default to undefined)
let updateOrganizationRequest: UpdateOrganizationRequest; //

const { status, data } = await apiInstance.updateOrganization(
    ifMatch,
    idempotencyKey,
    organizationId,
    updateOrganizationRequest
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **updateOrganizationRequest** | **UpdateOrganizationRequest**|  | |
| **ifMatch** | [**string**] | Weak ETag from a prior GET; rejects on mismatch with 412. | defaults to undefined|
| **idempotencyKey** | [**string**] | 24-hour idempotency key (idem_&lt;ulid&gt;). | defaults to undefined|
| **organizationId** | [**string**] |  | defaults to undefined|


### Return type

**OrganizationResponse**

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

