# NotificationWorkflowsApi

All URIs are relative to *https://dev.example.saas.omarss.net*

|Method | HTTP request | Description|
|------------- | ------------- | -------------|
|[**listNotificationWorkflows**](#listnotificationworkflows) | **GET** /v1/notification-workflows | List registered notification workflows for the caller\&#39;s tenant.|
|[**registerNotificationWorkflow**](#registernotificationworkflow) | **POST** /v1/notification-workflows | Register a (name → Novu workflow id) mapping.|
|[**updateNotificationWorkflow**](#updatenotificationworkflow) | **PATCH** /v1/notification-workflows/{workflow_id} | Update the Novu workflow id and/or description for a registered workflow.|

# **listNotificationWorkflows**
> NotificationWorkflowListResponse listNotificationWorkflows()


### Example

```typescript
import {
    NotificationWorkflowsApi,
    Configuration
} from '@omarss/saas-dataplane-sdk';

const configuration = new Configuration();
const apiInstance = new NotificationWorkflowsApi(configuration);

const { status, data } = await apiInstance.listNotificationWorkflows();
```

### Parameters
This endpoint does not have any parameters.


### Return type

**NotificationWorkflowListResponse**

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

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **registerNotificationWorkflow**
> NotificationWorkflowResponse registerNotificationWorkflow(registerNotificationWorkflowRequest)


### Example

```typescript
import {
    NotificationWorkflowsApi,
    Configuration,
    RegisterNotificationWorkflowRequest
} from '@omarss/saas-dataplane-sdk';

const configuration = new Configuration();
const apiInstance = new NotificationWorkflowsApi(configuration);

let idempotencyKey: string; //24-hour idempotency key (idem_<ulid>). (default to undefined)
let registerNotificationWorkflowRequest: RegisterNotificationWorkflowRequest; //

const { status, data } = await apiInstance.registerNotificationWorkflow(
    idempotencyKey,
    registerNotificationWorkflowRequest
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **registerNotificationWorkflowRequest** | **RegisterNotificationWorkflowRequest**|  | |
| **idempotencyKey** | [**string**] | 24-hour idempotency key (idem_&lt;ulid&gt;). | defaults to undefined|


### Return type

**NotificationWorkflowResponse**

### Authorization

[apiKeyAuth](../README.md#apiKeyAuth), [bearerAuth](../README.md#bearerAuth)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json, application/problem+json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
|**201** | Created |  -  |
|**401** | Missing or invalid bearer token / API key. |  -  |
|**422** | Idempotency-Key reused with a different body, OR validation failed. |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **updateNotificationWorkflow**
> NotificationWorkflowResponse updateNotificationWorkflow(updateNotificationWorkflowRequest)

Partial-update endpoint. Either field may be omitted to leave it unchanged. Emits a `notification_workflow.updated` outbox event so downstream consumers can refresh their cache. Workflow renames (changing the `name`) are not supported in v1 — register a new workflow with the new name and deprecate the old one. 

### Example

```typescript
import {
    NotificationWorkflowsApi,
    Configuration,
    UpdateNotificationWorkflowRequest
} from '@omarss/saas-dataplane-sdk';

const configuration = new Configuration();
const apiInstance = new NotificationWorkflowsApi(configuration);

let workflowId: string; // (default to undefined)
let updateNotificationWorkflowRequest: UpdateNotificationWorkflowRequest; //

const { status, data } = await apiInstance.updateNotificationWorkflow(
    workflowId,
    updateNotificationWorkflowRequest
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **updateNotificationWorkflowRequest** | **UpdateNotificationWorkflowRequest**|  | |
| **workflowId** | [**string**] |  | defaults to undefined|


### Return type

**NotificationWorkflowResponse**

### Authorization

[apiKeyAuth](../README.md#apiKeyAuth), [bearerAuth](../README.md#bearerAuth)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json, application/problem+json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
|**200** | OK |  -  |
|**401** | Missing or invalid bearer token / API key. |  -  |
|**403** | Caller lacks permission for this resource. |  -  |
|**404** | Resource not found. |  -  |
|**422** | Idempotency-Key reused with a different body, OR validation failed. |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

