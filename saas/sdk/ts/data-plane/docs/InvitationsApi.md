# InvitationsApi

All URIs are relative to *https://dev.example.saas.omarss.net*

|Method | HTTP request | Description|
|------------- | ------------- | -------------|
|[**acceptInvitation**](#acceptinvitation) | **POST** /v1/invitations/{invitation_id}/accept | Accept a pending invitation. Creates the Member row.|
|[**createInvitation**](#createinvitation) | **POST** /v1/organizations/{organization_id}/invitations | Create an invitation. Email is queued; plaintext token returned ONCE.|
|[**getInvitation**](#getinvitation) | **GET** /v1/invitations/{invitation_id} | Fetch an invitation by id. Plaintext token never echoed.|
|[**listInvitations**](#listinvitations) | **GET** /v1/organizations/{organization_id}/invitations | List invitations for an organization.|
|[**revokeInvitation**](#revokeinvitation) | **DELETE** /v1/invitations/{invitation_id} | Revoke a pending invitation. Returns 204.|

# **acceptInvitation**
> MemberResponse acceptInvitation(acceptInvitationRequest)

Consumes a one-time accept token. The caller\'s JWT supplies the user identity; the invitation\'s stored tenant_id is constant-time-compared to the caller\'s tenant. Returns the newly-created Member. 

### Example

```typescript
import {
    InvitationsApi,
    Configuration,
    AcceptInvitationRequest
} from '@omarss/saas-dataplane-sdk';

const configuration = new Configuration();
const apiInstance = new InvitationsApi(configuration);

let idempotencyKey: string; //24-hour idempotency key (idem_<ulid>). (default to undefined)
let invitationId: string; // (default to undefined)
let acceptInvitationRequest: AcceptInvitationRequest; //

const { status, data } = await apiInstance.acceptInvitation(
    idempotencyKey,
    invitationId,
    acceptInvitationRequest
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **acceptInvitationRequest** | **AcceptInvitationRequest**|  | |
| **idempotencyKey** | [**string**] | 24-hour idempotency key (idem_&lt;ulid&gt;). | defaults to undefined|
| **invitationId** | [**string**] |  | defaults to undefined|


### Return type

**MemberResponse**

### Authorization

[apiKeyAuth](../README.md#apiKeyAuth), [bearerAuth](../README.md#bearerAuth)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json, application/problem+json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
|**200** | Member created; invitation consumed. |  -  |
|**401** | Missing or invalid bearer token / API key. |  -  |
|**403** | Caller lacks permission for this resource. |  -  |
|**404** | Resource not found. |  -  |
|**410** | Invitation already consumed, revoked, or expired. |  -  |
|**422** | Idempotency-Key reused with a different body, OR validation failed. |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **createInvitation**
> CreateInvitationResponse createInvitation(createInvitationRequest)

Returns 202 Accepted because the email dispatch is queued via the Notifications module. The response carries `accept_url` and the one-time plaintext token alongside `state` + `expires_at`; subsequent reads of this invitation return only the `token_prefix`. Never log the response body. 

### Example

```typescript
import {
    InvitationsApi,
    Configuration,
    CreateInvitationRequest
} from '@omarss/saas-dataplane-sdk';

const configuration = new Configuration();
const apiInstance = new InvitationsApi(configuration);

let idempotencyKey: string; //24-hour idempotency key (idem_<ulid>). (default to undefined)
let organizationId: string; // (default to undefined)
let createInvitationRequest: CreateInvitationRequest; //

const { status, data } = await apiInstance.createInvitation(
    idempotencyKey,
    organizationId,
    createInvitationRequest
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **createInvitationRequest** | **CreateInvitationRequest**|  | |
| **idempotencyKey** | [**string**] | 24-hour idempotency key (idem_&lt;ulid&gt;). | defaults to undefined|
| **organizationId** | [**string**] |  | defaults to undefined|


### Return type

**CreateInvitationResponse**

### Authorization

[apiKeyAuth](../README.md#apiKeyAuth), [bearerAuth](../README.md#bearerAuth)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json, application/problem+json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
|**202** | Accepted; invitation persisted + email queued. |  -  |
|**401** | Missing or invalid bearer token / API key. |  -  |
|**403** | Caller lacks permission for this resource. |  -  |
|**404** | Resource not found. |  -  |
|**409** | Concurrent request with the same Idempotency-Key is still processing. |  -  |
|**422** | Idempotency-Key reused with a different body, OR validation failed. |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **getInvitation**
> InvitationResponse getInvitation()


### Example

```typescript
import {
    InvitationsApi,
    Configuration
} from '@omarss/saas-dataplane-sdk';

const configuration = new Configuration();
const apiInstance = new InvitationsApi(configuration);

let invitationId: string; // (default to undefined)

const { status, data } = await apiInstance.getInvitation(
    invitationId
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **invitationId** | [**string**] |  | defaults to undefined|


### Return type

**InvitationResponse**

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

# **listInvitations**
> InvitationListResponse listInvitations()


### Example

```typescript
import {
    InvitationsApi,
    Configuration
} from '@omarss/saas-dataplane-sdk';

const configuration = new Configuration();
const apiInstance = new InvitationsApi(configuration);

let organizationId: string; // (default to undefined)
let limit: number; //Max items to return (default 25, max 200). (optional) (default to 25)

const { status, data } = await apiInstance.listInvitations(
    organizationId,
    limit
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **organizationId** | [**string**] |  | defaults to undefined|
| **limit** | [**number**] | Max items to return (default 25, max 200). | (optional) defaults to 25|


### Return type

**InvitationListResponse**

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

# **revokeInvitation**
> revokeInvitation()


### Example

```typescript
import {
    InvitationsApi,
    Configuration
} from '@omarss/saas-dataplane-sdk';

const configuration = new Configuration();
const apiInstance = new InvitationsApi(configuration);

let ifMatch: string; //Weak ETag from a prior GET; rejects on mismatch with 412. (default to undefined)
let invitationId: string; // (default to undefined)

const { status, data } = await apiInstance.revokeInvitation(
    ifMatch,
    invitationId
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **ifMatch** | [**string**] | Weak ETag from a prior GET; rejects on mismatch with 412. | defaults to undefined|
| **invitationId** | [**string**] |  | defaults to undefined|


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
|**410** | Invitation already consumed or expired. |  -  |
|**412** | If-Match header missing or stale. |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

