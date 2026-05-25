# DomainsApi

All URIs are relative to *https://control.saas.omarss.net*

|Method | HTTP request | Description|
|------------- | ------------- | -------------|
|[**attachDeploymentDomain**](#attachdeploymentdomain) | **POST** /control/v1/deployments/{deployment_id}/domains | |
|[**detachDeploymentDomain**](#detachdeploymentdomain) | **DELETE** /control/v1/deployments/{deployment_id}/domains/{domain_id} | |
|[**getDeploymentDomain**](#getdeploymentdomain) | **GET** /control/v1/deployments/{deployment_id}/domains/{domain_id} | |
|[**listDeploymentDomains**](#listdeploymentdomains) | **GET** /control/v1/deployments/{deployment_id}/domains | |
|[**verifyDeploymentDomain**](#verifydeploymentdomain) | **POST** /control/v1/deployments/{deployment_id}/domains/{domain_id}/verify | |

# **attachDeploymentDomain**
> DeploymentDomainResponse attachDeploymentDomain(attachDomainRequest)


### Example

```typescript
import {
    DomainsApi,
    Configuration,
    AttachDomainRequest
} from '@omarss/saas-controlplane-sdk';

const configuration = new Configuration();
const apiInstance = new DomainsApi(configuration);

let idempotencyKey: string; // (default to undefined)
let deploymentId: string; // (default to undefined)
let attachDomainRequest: AttachDomainRequest; //

const { status, data } = await apiInstance.attachDeploymentDomain(
    idempotencyKey,
    deploymentId,
    attachDomainRequest
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **attachDomainRequest** | **AttachDomainRequest**|  | |
| **idempotencyKey** | [**string**] |  | defaults to undefined|
| **deploymentId** | [**string**] |  | defaults to undefined|


### Return type

**DeploymentDomainResponse**

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
|**201** | Created; verification record returned. |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **detachDeploymentDomain**
> detachDeploymentDomain()


### Example

```typescript
import {
    DomainsApi,
    Configuration
} from '@omarss/saas-controlplane-sdk';

const configuration = new Configuration();
const apiInstance = new DomainsApi(configuration);

let deploymentId: string; // (default to undefined)
let domainId: string; // (default to undefined)
let ifMatch: string; // (optional) (default to undefined)

const { status, data } = await apiInstance.detachDeploymentDomain(
    deploymentId,
    domainId,
    ifMatch
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **deploymentId** | [**string**] |  | defaults to undefined|
| **domainId** | [**string**] |  | defaults to undefined|
| **ifMatch** | [**string**] |  | (optional) defaults to undefined|


### Return type

void (empty response body)

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: Not defined


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
|**204** | Detached. |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **getDeploymentDomain**
> DeploymentDomainResponse getDeploymentDomain()


### Example

```typescript
import {
    DomainsApi,
    Configuration
} from '@omarss/saas-controlplane-sdk';

const configuration = new Configuration();
const apiInstance = new DomainsApi(configuration);

let deploymentId: string; // (default to undefined)
let domainId: string; // (default to undefined)

const { status, data } = await apiInstance.getDeploymentDomain(
    deploymentId,
    domainId
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **deploymentId** | [**string**] |  | defaults to undefined|
| **domainId** | [**string**] |  | defaults to undefined|


### Return type

**DeploymentDomainResponse**

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
|**200** | OK |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **listDeploymentDomains**
> DeploymentDomainListResponse listDeploymentDomains()


### Example

```typescript
import {
    DomainsApi,
    Configuration
} from '@omarss/saas-controlplane-sdk';

const configuration = new Configuration();
const apiInstance = new DomainsApi(configuration);

let deploymentId: string; // (default to undefined)

const { status, data } = await apiInstance.listDeploymentDomains(
    deploymentId
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **deploymentId** | [**string**] |  | defaults to undefined|


### Return type

**DeploymentDomainListResponse**

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
|**200** | OK |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **verifyDeploymentDomain**
> DeploymentDomainResponse verifyDeploymentDomain()


### Example

```typescript
import {
    DomainsApi,
    Configuration
} from '@omarss/saas-controlplane-sdk';

const configuration = new Configuration();
const apiInstance = new DomainsApi(configuration);

let idempotencyKey: string; // (default to undefined)
let deploymentId: string; // (default to undefined)
let domainId: string; // (default to undefined)

const { status, data } = await apiInstance.verifyDeploymentDomain(
    idempotencyKey,
    deploymentId,
    domainId
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **idempotencyKey** | [**string**] |  | defaults to undefined|
| **deploymentId** | [**string**] |  | defaults to undefined|
| **domainId** | [**string**] |  | defaults to undefined|


### Return type

**DeploymentDomainResponse**

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
|**200** | Verification attempted; check status field. |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

