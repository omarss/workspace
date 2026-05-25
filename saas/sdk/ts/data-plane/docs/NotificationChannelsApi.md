# NotificationChannelsApi

All URIs are relative to *https://dev.example.saas.omarss.net*

|Method | HTTP request | Description|
|------------- | ------------- | -------------|
|[**createNotificationChannel**](#createnotificationchannel) | **POST** /v1/notification-channels | Create a BYOK notification channel.|
|[**deleteNotificationChannel**](#deletenotificationchannel) | **DELETE** /v1/notification-channels/{channel_id} | Soft-delete a notification channel.|
|[**getNotificationChannel**](#getnotificationchannel) | **GET** /v1/notification-channels/{channel_id} | Fetch a notification channel by id.|
|[**listNotificationChannels**](#listnotificationchannels) | **GET** /v1/notification-channels | List BYOK notification channels in the caller\&#39;s tenant.|
|[**rotateNotificationChannelCredentials**](#rotatenotificationchannelcredentials) | **POST** /v1/notification-channels/{channel_id}/rotate-credentials | Rotate a channel\&#39;s BYOK credentials.|
|[**updateNotificationChannel**](#updatenotificationchannel) | **PATCH** /v1/notification-channels/{channel_id} | Update a notification channel (metadata only).|

# **createNotificationChannel**
> NotificationChannelResponse createNotificationChannel(createNotificationChannelRequest)

Idempotent. Per ADR 017 credentials in the body are envelope-encrypted before the row is inserted and the persisted plaintext is zeroed immediately. The response NEVER echoes credentials — only a credentials_present flag and last_rotated_at timestamp. 

### Example

```typescript
import {
    NotificationChannelsApi,
    Configuration,
    CreateNotificationChannelRequest
} from '@omarss/saas-dataplane-sdk';

const configuration = new Configuration();
const apiInstance = new NotificationChannelsApi(configuration);

let idempotencyKey: string; //24-hour idempotency key (idem_<ulid>). (default to undefined)
let createNotificationChannelRequest: CreateNotificationChannelRequest; //

const { status, data } = await apiInstance.createNotificationChannel(
    idempotencyKey,
    createNotificationChannelRequest
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **createNotificationChannelRequest** | **CreateNotificationChannelRequest**|  | |
| **idempotencyKey** | [**string**] | 24-hour idempotency key (idem_&lt;ulid&gt;). | defaults to undefined|


### Return type

**NotificationChannelResponse**

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

# **deleteNotificationChannel**
> deleteNotificationChannel()


### Example

```typescript
import {
    NotificationChannelsApi,
    Configuration
} from '@omarss/saas-dataplane-sdk';

const configuration = new Configuration();
const apiInstance = new NotificationChannelsApi(configuration);

let ifMatch: string; //Weak ETag from a prior GET; rejects on mismatch with 412. (default to undefined)
let channelId: string; // (default to undefined)

const { status, data } = await apiInstance.deleteNotificationChannel(
    ifMatch,
    channelId
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **ifMatch** | [**string**] | Weak ETag from a prior GET; rejects on mismatch with 412. | defaults to undefined|
| **channelId** | [**string**] |  | defaults to undefined|


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

# **getNotificationChannel**
> NotificationChannelResponse getNotificationChannel()


### Example

```typescript
import {
    NotificationChannelsApi,
    Configuration
} from '@omarss/saas-dataplane-sdk';

const configuration = new Configuration();
const apiInstance = new NotificationChannelsApi(configuration);

let channelId: string; // (default to undefined)

const { status, data } = await apiInstance.getNotificationChannel(
    channelId
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **channelId** | [**string**] |  | defaults to undefined|


### Return type

**NotificationChannelResponse**

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

# **listNotificationChannels**
> NotificationChannelListResponse listNotificationChannels()


### Example

```typescript
import {
    NotificationChannelsApi,
    Configuration
} from '@omarss/saas-dataplane-sdk';

const configuration = new Configuration();
const apiInstance = new NotificationChannelsApi(configuration);

let limit: number; //Max items to return (default 25, max 200). (optional) (default to 25)

const { status, data } = await apiInstance.listNotificationChannels(
    limit
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **limit** | [**number**] | Max items to return (default 25, max 200). | (optional) defaults to 25|


### Return type

**NotificationChannelListResponse**

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

# **rotateNotificationChannelCredentials**
> NotificationChannelResponse rotateNotificationChannelCredentials(rotateChannelCredentialsRequest)

ADR 017: rotation is the only verb that accepts new credentials. Bumps row_seq and stamps last_rotated_at; emits the notification_channel.rotated audit event. 

### Example

```typescript
import {
    NotificationChannelsApi,
    Configuration,
    RotateChannelCredentialsRequest
} from '@omarss/saas-dataplane-sdk';

const configuration = new Configuration();
const apiInstance = new NotificationChannelsApi(configuration);

let idempotencyKey: string; //24-hour idempotency key (idem_<ulid>). (default to undefined)
let channelId: string; // (default to undefined)
let rotateChannelCredentialsRequest: RotateChannelCredentialsRequest; //

const { status, data } = await apiInstance.rotateNotificationChannelCredentials(
    idempotencyKey,
    channelId,
    rotateChannelCredentialsRequest
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **rotateChannelCredentialsRequest** | **RotateChannelCredentialsRequest**|  | |
| **idempotencyKey** | [**string**] | 24-hour idempotency key (idem_&lt;ulid&gt;). | defaults to undefined|
| **channelId** | [**string**] |  | defaults to undefined|


### Return type

**NotificationChannelResponse**

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
|**422** | Idempotency-Key reused with a different body, OR validation failed. |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **updateNotificationChannel**
> NotificationChannelResponse updateNotificationChannel(updateNotificationChannelRequest)

Per ADR 017 PATCH never accepts credentials. Use the dedicated rotate-credentials endpoint to change secrets. 

### Example

```typescript
import {
    NotificationChannelsApi,
    Configuration,
    UpdateNotificationChannelRequest
} from '@omarss/saas-dataplane-sdk';

const configuration = new Configuration();
const apiInstance = new NotificationChannelsApi(configuration);

let ifMatch: string; //Weak ETag from a prior GET; rejects on mismatch with 412. (default to undefined)
let idempotencyKey: string; //24-hour idempotency key (idem_<ulid>). (default to undefined)
let channelId: string; // (default to undefined)
let updateNotificationChannelRequest: UpdateNotificationChannelRequest; //

const { status, data } = await apiInstance.updateNotificationChannel(
    ifMatch,
    idempotencyKey,
    channelId,
    updateNotificationChannelRequest
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **updateNotificationChannelRequest** | **UpdateNotificationChannelRequest**|  | |
| **ifMatch** | [**string**] | Weak ETag from a prior GET; rejects on mismatch with 412. | defaults to undefined|
| **idempotencyKey** | [**string**] | 24-hour idempotency key (idem_&lt;ulid&gt;). | defaults to undefined|
| **channelId** | [**string**] |  | defaults to undefined|


### Return type

**NotificationChannelResponse**

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

