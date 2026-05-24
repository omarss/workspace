# SocialProvidersApi

All URIs are relative to *https://dev.example.saas.omarss.net*

|Method | HTTP request | Description|
|------------- | ------------- | -------------|
|[**linkSocialProvider**](#linksocialprovider) | **POST** /v1/users/{user_id}/social-providers | Start a social-provider link flow. Returns the Keycloak link URL.|
|[**listSocialProviders**](#listsocialproviders) | **GET** /v1/users/{user_id}/social-providers | List linked social providers for a user.|
|[**unlinkSocialProvider**](#unlinksocialprovider) | **DELETE** /v1/users/{user_id}/social-providers/{provider} | Unlink a social provider. Emits user.social_unlinked.|

# **linkSocialProvider**
> LinkSocialProviderResponse linkSocialProvider(linkSocialProviderRequest)

Per ADR 014: we never call CreateUserFederatedIdentity from a user-facing endpoint (no proof-of-possession). Instead, the platform mints Keycloak\'s hashed link URL — the caller redirects the user\'s browser there and Keycloak completes the OAuth dance with the external IdP, writing the federated_identity row itself. 

### Example

```typescript
import {
    SocialProvidersApi,
    Configuration,
    LinkSocialProviderRequest
} from '@omarss/saas-dataplane-sdk';

const configuration = new Configuration();
const apiInstance = new SocialProvidersApi(configuration);

let idempotencyKey: string; //24-hour idempotency key (idem_<ulid>). (default to undefined)
let userId: string; // (default to undefined)
let linkSocialProviderRequest: LinkSocialProviderRequest; //

const { status, data } = await apiInstance.linkSocialProvider(
    idempotencyKey,
    userId,
    linkSocialProviderRequest
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **linkSocialProviderRequest** | **LinkSocialProviderRequest**|  | |
| **idempotencyKey** | [**string**] | 24-hour idempotency key (idem_&lt;ulid&gt;). | defaults to undefined|
| **userId** | [**string**] |  | defaults to undefined|


### Return type

**LinkSocialProviderResponse**

### Authorization

[apiKeyAuth](../README.md#apiKeyAuth), [bearerAuth](../README.md#bearerAuth)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json, application/problem+json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
|**202** | Accepted; caller must redirect to authorization_url. |  -  |
|**401** | Missing or invalid bearer token / API key. |  -  |
|**403** | Caller lacks permission for this resource. |  -  |
|**404** | Resource not found. |  -  |
|**422** | Idempotency-Key reused with a different body, OR validation failed. |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **listSocialProviders**
> SocialProviderListResponse listSocialProviders()


### Example

```typescript
import {
    SocialProvidersApi,
    Configuration
} from '@omarss/saas-dataplane-sdk';

const configuration = new Configuration();
const apiInstance = new SocialProvidersApi(configuration);

let userId: string; // (default to undefined)

const { status, data } = await apiInstance.listSocialProviders(
    userId
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **userId** | [**string**] |  | defaults to undefined|


### Return type

**SocialProviderListResponse**

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

# **unlinkSocialProvider**
> unlinkSocialProvider()


### Example

```typescript
import {
    SocialProvidersApi,
    Configuration
} from '@omarss/saas-dataplane-sdk';

const configuration = new Configuration();
const apiInstance = new SocialProvidersApi(configuration);

let userId: string; // (default to undefined)
let provider: 'google' | 'github' | 'apple'; // (default to undefined)

const { status, data } = await apiInstance.unlinkSocialProvider(
    userId,
    provider
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **userId** | [**string**] |  | defaults to undefined|
| **provider** | [**&#39;google&#39; | &#39;github&#39; | &#39;apple&#39;**]**Array<&#39;google&#39; &#124; &#39;github&#39; &#124; &#39;apple&#39;>** |  | defaults to undefined|


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
|**204** | Unlinked. |  -  |
|**401** | Missing or invalid bearer token / API key. |  -  |
|**403** | Caller lacks permission for this resource. |  -  |
|**404** | Resource not found. |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

