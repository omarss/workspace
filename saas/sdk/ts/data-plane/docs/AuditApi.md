# AuditApi

All URIs are relative to *https://dev.example.saas.omarss.net*

|Method | HTTP request | Description|
|------------- | ------------- | -------------|
|[**exportAuditEvents**](#exportauditevents) | **POST** /v1/audit-events/export | Export filtered audit events as JSON or CSV.|
|[**getAuditEvent**](#getauditevent) | **GET** /v1/audit-events/{audit_event_id} | Fetch a single audit event by id.|
|[**listAuditEvents**](#listauditevents) | **GET** /v1/tenants/{tenant_id}/audit-events | List audit events for a tenant.|

# **exportAuditEvents**
> AuditEventListResponse exportAuditEvents(exportAuditEventsRequest)

Synchronous export bounded to ExportSyncBudget (1 MiB). Larger exports return 413; the async export path (background worker + signed URL) lands with the v1 Files module. 

### Example

```typescript
import {
    AuditApi,
    Configuration,
    ExportAuditEventsRequest
} from '@omarss/saas-dataplane-sdk';

const configuration = new Configuration();
const apiInstance = new AuditApi(configuration);

let exportAuditEventsRequest: ExportAuditEventsRequest; //

const { status, data } = await apiInstance.exportAuditEvents(
    exportAuditEventsRequest
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **exportAuditEventsRequest** | **ExportAuditEventsRequest**|  | |


### Return type

**AuditEventListResponse**

### Authorization

[apiKeyAuth](../README.md#apiKeyAuth), [bearerAuth](../README.md#bearerAuth)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json, text/csv, application/problem+json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
|**200** | Inline export. |  -  |
|**401** | Missing or invalid bearer token / API key. |  -  |
|**403** | Caller lacks permission for this resource. |  -  |
|**413** | Export exceeds sync size budget. |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **getAuditEvent**
> AuditEventResponse getAuditEvent()


### Example

```typescript
import {
    AuditApi,
    Configuration
} from '@omarss/saas-dataplane-sdk';

const configuration = new Configuration();
const apiInstance = new AuditApi(configuration);

let auditEventId: string; // (default to undefined)

const { status, data } = await apiInstance.getAuditEvent(
    auditEventId
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **auditEventId** | [**string**] |  | defaults to undefined|


### Return type

**AuditEventResponse**

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

# **listAuditEvents**
> AuditEventListResponse listAuditEvents()

Returns audit events ordered by occurred_at DESC. MVP gates this endpoint with AssertTenant only; the audit.read permission lands with the v1 RBAC hardening pass (ADR 012). 

### Example

```typescript
import {
    AuditApi,
    Configuration
} from '@omarss/saas-dataplane-sdk';

const configuration = new Configuration();
const apiInstance = new AuditApi(configuration);

let tenantId: string; // (default to undefined)
let limit: number; //Max items to return (default 25, max 200). (optional) (default to 25)
let cursor: string; //Opaque pagination cursor; obtained from a previous response. (optional) (default to undefined)
let action: string; // (optional) (default to undefined)
let resourceType: string; // (optional) (default to undefined)
let resourceId: string; // (optional) (default to undefined)
let actorId: string; // (optional) (default to undefined)
let occurredAfter: string; // (optional) (default to undefined)
let occurredBefore: string; // (optional) (default to undefined)

const { status, data } = await apiInstance.listAuditEvents(
    tenantId,
    limit,
    cursor,
    action,
    resourceType,
    resourceId,
    actorId,
    occurredAfter,
    occurredBefore
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **tenantId** | [**string**] |  | defaults to undefined|
| **limit** | [**number**] | Max items to return (default 25, max 200). | (optional) defaults to 25|
| **cursor** | [**string**] | Opaque pagination cursor; obtained from a previous response. | (optional) defaults to undefined|
| **action** | [**string**] |  | (optional) defaults to undefined|
| **resourceType** | [**string**] |  | (optional) defaults to undefined|
| **resourceId** | [**string**] |  | (optional) defaults to undefined|
| **actorId** | [**string**] |  | (optional) defaults to undefined|
| **occurredAfter** | [**string**] |  | (optional) defaults to undefined|
| **occurredBefore** | [**string**] |  | (optional) defaults to undefined|


### Return type

**AuditEventListResponse**

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

