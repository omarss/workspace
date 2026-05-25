# NotificationsApi

All URIs are relative to *https://dev.example.saas.omarss.net*

|Method | HTTP request | Description|
|------------- | ------------- | -------------|
|[**getNotification**](#getnotification) | **GET** /v1/notifications/{notification_id} | Fetch a notification by id.|
|[**listNotifications**](#listnotifications) | **GET** /v1/notifications | List notifications in the caller\&#39;s tenant.|
|[**sendNotification**](#sendnotification) | **POST** /v1/notifications/send | Queue a notification for delivery via Novu.|

# **getNotification**
> NotificationResponse getNotification()


### Example

```typescript
import {
    NotificationsApi,
    Configuration
} from '@omarss/saas-dataplane-sdk';

const configuration = new Configuration();
const apiInstance = new NotificationsApi(configuration);

let notificationId: string; // (default to undefined)

const { status, data } = await apiInstance.getNotification(
    notificationId
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **notificationId** | [**string**] |  | defaults to undefined|


### Return type

**NotificationResponse**

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

# **listNotifications**
> NotificationListResponse listNotifications()


### Example

```typescript
import {
    NotificationsApi,
    Configuration
} from '@omarss/saas-dataplane-sdk';

const configuration = new Configuration();
const apiInstance = new NotificationsApi(configuration);

let limit: number; //Max items to return (default 25, max 200). (optional) (default to 25)
let cursor: string; //Opaque pagination cursor; obtained from a previous response. (optional) (default to undefined)

const { status, data } = await apiInstance.listNotifications(
    limit,
    cursor
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **limit** | [**number**] | Max items to return (default 25, max 200). | (optional) defaults to 25|
| **cursor** | [**string**] | Opaque pagination cursor; obtained from a previous response. | (optional) defaults to undefined|


### Return type

**NotificationListResponse**

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

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **sendNotification**
> NotificationResponse sendNotification(sendNotificationRequest)

Returns 202 Accepted; Novu trigger happens via the outbox worker so Novu downtime does not block the request response. Status transitions live on the worker — clients poll GET /v1/notifications/{id}. 

### Example

```typescript
import {
    NotificationsApi,
    Configuration,
    SendNotificationRequest
} from '@omarss/saas-dataplane-sdk';

const configuration = new Configuration();
const apiInstance = new NotificationsApi(configuration);

let idempotencyKey: string; //24-hour idempotency key (idem_<ulid>). (default to undefined)
let sendNotificationRequest: SendNotificationRequest; //

const { status, data } = await apiInstance.sendNotification(
    idempotencyKey,
    sendNotificationRequest
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **sendNotificationRequest** | **SendNotificationRequest**|  | |
| **idempotencyKey** | [**string**] | 24-hour idempotency key (idem_&lt;ulid&gt;). | defaults to undefined|


### Return type

**NotificationResponse**

### Authorization

[apiKeyAuth](../README.md#apiKeyAuth), [bearerAuth](../README.md#bearerAuth)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json, application/problem+json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
|**202** | Accepted; notification queued. |  -  |
|**401** | Missing or invalid bearer token / API key. |  -  |
|**404** | Resource not found. |  -  |
|**422** | Idempotency-Key reused with a different body, OR validation failed. |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

