# DeploymentsApi

All URIs are relative to *https://control.saas.omarss.net*

|Method | HTTP request | Description|
|------------- | ------------- | -------------|
|[**createDeployment**](#createdeployment) | **POST** /control/v1/deployments | Provision a new Deployment.|
|[**deleteDeployment**](#deletedeployment) | **DELETE** /control/v1/deployments/{deployment_id} | |
|[**freezeDeploymentKeys**](#freezedeploymentkeys) | **POST** /control/v1/deployments/{deployment_id}/freeze-keys | |
|[**getDeployment**](#getdeployment) | **GET** /control/v1/deployments/{deployment_id} | |
|[**getDeploymentHealth**](#getdeploymenthealth) | **GET** /control/v1/deployments/{deployment_id}/health | |
|[**listDeploymentRevisions**](#listdeploymentrevisions) | **GET** /control/v1/deployments/{deployment_id}/revisions | |
|[**listDeployments**](#listdeployments) | **GET** /control/v1/deployments | List Deployments.|
|[**purgeDeployment**](#purgedeployment) | **POST** /control/v1/deployments/{deployment_id}/purge | |
|[**restartDeployment**](#restartdeployment) | **POST** /control/v1/deployments/{deployment_id}/restart | |
|[**restoreDeployment**](#restoredeployment) | **POST** /control/v1/deployments/{deployment_id}/restore | |
|[**rollbackDeployment**](#rollbackdeployment) | **POST** /control/v1/deployments/{deployment_id}/rollback | |
|[**startImpersonationSession**](#startimpersonationsession) | **POST** /control/v1/deployments/{deployment_id}/impersonation-sessions | |
|[**tailDeploymentLogs**](#taildeploymentlogs) | **GET** /control/v1/deployments/{deployment_id}/logs | |
|[**updateDeployment**](#updatedeployment) | **PATCH** /control/v1/deployments/{deployment_id} | |
|[**upgradeDeployment**](#upgradedeployment) | **POST** /control/v1/deployments/{deployment_id}/upgrade | |

# **createDeployment**
> CreateDeploymentResponse createDeployment(createDeploymentRequest)


### Example

```typescript
import {
    DeploymentsApi,
    Configuration,
    CreateDeploymentRequest
} from '@omarss/saas-controlplane-sdk';

const configuration = new Configuration();
const apiInstance = new DeploymentsApi(configuration);

let idempotencyKey: string; // (default to undefined)
let createDeploymentRequest: CreateDeploymentRequest; //

const { status, data } = await apiInstance.createDeployment(
    idempotencyKey,
    createDeploymentRequest
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **createDeploymentRequest** | **CreateDeploymentRequest**|  | |
| **idempotencyKey** | [**string**] |  | defaults to undefined|


### Return type

**CreateDeploymentResponse**

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
|**201** | Created. |  * ETag -  <br>  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **deleteDeployment**
> deleteDeployment()


### Example

```typescript
import {
    DeploymentsApi,
    Configuration
} from '@omarss/saas-controlplane-sdk';

const configuration = new Configuration();
const apiInstance = new DeploymentsApi(configuration);

let deploymentId: string; // (default to undefined)
let retainDays: number; // (optional) (default to 30)

const { status, data } = await apiInstance.deleteDeployment(
    deploymentId,
    retainDays
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **deploymentId** | [**string**] |  | defaults to undefined|
| **retainDays** | [**number**] |  | (optional) defaults to 30|


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
|**204** | Soft-deleted; retention applies. |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **freezeDeploymentKeys**
> DeploymentResponse freezeDeploymentKeys()


### Example

```typescript
import {
    DeploymentsApi,
    Configuration
} from '@omarss/saas-controlplane-sdk';

const configuration = new Configuration();
const apiInstance = new DeploymentsApi(configuration);

let idempotencyKey: string; // (default to undefined)
let deploymentId: string; // (default to undefined)

const { status, data } = await apiInstance.freezeDeploymentKeys(
    idempotencyKey,
    deploymentId
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **idempotencyKey** | [**string**] |  | defaults to undefined|
| **deploymentId** | [**string**] |  | defaults to undefined|


### Return type

**DeploymentResponse**

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
|**202** | Accepted; subsequent API key rotations refused. |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **getDeployment**
> DeploymentResponse getDeployment()


### Example

```typescript
import {
    DeploymentsApi,
    Configuration
} from '@omarss/saas-controlplane-sdk';

const configuration = new Configuration();
const apiInstance = new DeploymentsApi(configuration);

let deploymentId: string; // (default to undefined)

const { status, data } = await apiInstance.getDeployment(
    deploymentId
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **deploymentId** | [**string**] |  | defaults to undefined|


### Return type

**DeploymentResponse**

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

# **getDeploymentHealth**
> DeploymentHealthResponse getDeploymentHealth()


### Example

```typescript
import {
    DeploymentsApi,
    Configuration
} from '@omarss/saas-controlplane-sdk';

const configuration = new Configuration();
const apiInstance = new DeploymentsApi(configuration);

let deploymentId: string; // (default to undefined)

const { status, data } = await apiInstance.getDeploymentHealth(
    deploymentId
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **deploymentId** | [**string**] |  | defaults to undefined|


### Return type

**DeploymentHealthResponse**

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

# **listDeploymentRevisions**
> DeploymentRevisionListResponse listDeploymentRevisions()


### Example

```typescript
import {
    DeploymentsApi,
    Configuration
} from '@omarss/saas-controlplane-sdk';

const configuration = new Configuration();
const apiInstance = new DeploymentsApi(configuration);

let deploymentId: string; // (default to undefined)

const { status, data } = await apiInstance.listDeploymentRevisions(
    deploymentId
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **deploymentId** | [**string**] |  | defaults to undefined|


### Return type

**DeploymentRevisionListResponse**

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

# **listDeployments**
> DeploymentListResponse listDeployments()


### Example

```typescript
import {
    DeploymentsApi,
    Configuration
} from '@omarss/saas-controlplane-sdk';

const configuration = new Configuration();
const apiInstance = new DeploymentsApi(configuration);

let limit: number; // (optional) (default to 25)
let cursor: string; // (optional) (default to undefined)
let status: string; // (optional) (default to undefined)

const { status, data } = await apiInstance.listDeployments(
    limit,
    cursor,
    status
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **limit** | [**number**] |  | (optional) defaults to 25|
| **cursor** | [**string**] |  | (optional) defaults to undefined|
| **status** | [**string**] |  | (optional) defaults to undefined|


### Return type

**DeploymentListResponse**

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

# **purgeDeployment**
> DeploymentResponse purgeDeployment()


### Example

```typescript
import {
    DeploymentsApi,
    Configuration
} from '@omarss/saas-controlplane-sdk';

const configuration = new Configuration();
const apiInstance = new DeploymentsApi(configuration);

let idempotencyKey: string; // (default to undefined)
let deploymentId: string; // (default to undefined)

const { status, data } = await apiInstance.purgeDeployment(
    idempotencyKey,
    deploymentId
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **idempotencyKey** | [**string**] |  | defaults to undefined|
| **deploymentId** | [**string**] |  | defaults to undefined|


### Return type

**DeploymentResponse**

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
|**202** | Accepted |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **restartDeployment**
> DeploymentResponse restartDeployment()


### Example

```typescript
import {
    DeploymentsApi,
    Configuration
} from '@omarss/saas-controlplane-sdk';

const configuration = new Configuration();
const apiInstance = new DeploymentsApi(configuration);

let idempotencyKey: string; // (default to undefined)
let deploymentId: string; // (default to undefined)

const { status, data } = await apiInstance.restartDeployment(
    idempotencyKey,
    deploymentId
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **idempotencyKey** | [**string**] |  | defaults to undefined|
| **deploymentId** | [**string**] |  | defaults to undefined|


### Return type

**DeploymentResponse**

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
|**202** | Accepted |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **restoreDeployment**
> DeploymentResponse restoreDeployment(restoreDeploymentRequest)


### Example

```typescript
import {
    DeploymentsApi,
    Configuration,
    RestoreDeploymentRequest
} from '@omarss/saas-controlplane-sdk';

const configuration = new Configuration();
const apiInstance = new DeploymentsApi(configuration);

let idempotencyKey: string; // (default to undefined)
let deploymentId: string; // (default to undefined)
let restoreDeploymentRequest: RestoreDeploymentRequest; //

const { status, data } = await apiInstance.restoreDeployment(
    idempotencyKey,
    deploymentId,
    restoreDeploymentRequest
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **restoreDeploymentRequest** | **RestoreDeploymentRequest**|  | |
| **idempotencyKey** | [**string**] |  | defaults to undefined|
| **deploymentId** | [**string**] |  | defaults to undefined|


### Return type

**DeploymentResponse**

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
|**202** | Accepted |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **rollbackDeployment**
> DeploymentResponse rollbackDeployment()


### Example

```typescript
import {
    DeploymentsApi,
    Configuration
} from '@omarss/saas-controlplane-sdk';

const configuration = new Configuration();
const apiInstance = new DeploymentsApi(configuration);

let idempotencyKey: string; // (default to undefined)
let deploymentId: string; // (default to undefined)

const { status, data } = await apiInstance.rollbackDeployment(
    idempotencyKey,
    deploymentId
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **idempotencyKey** | [**string**] |  | defaults to undefined|
| **deploymentId** | [**string**] |  | defaults to undefined|


### Return type

**DeploymentResponse**

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
|**202** | Accepted |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **startImpersonationSession**
> StartImpersonationResponse startImpersonationSession(startImpersonationRequest)


### Example

```typescript
import {
    DeploymentsApi,
    Configuration,
    StartImpersonationRequest
} from '@omarss/saas-controlplane-sdk';

const configuration = new Configuration();
const apiInstance = new DeploymentsApi(configuration);

let idempotencyKey: string; // (default to undefined)
let deploymentId: string; // (default to undefined)
let startImpersonationRequest: StartImpersonationRequest; //

const { status, data } = await apiInstance.startImpersonationSession(
    idempotencyKey,
    deploymentId,
    startImpersonationRequest
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **startImpersonationRequest** | **StartImpersonationRequest**|  | |
| **idempotencyKey** | [**string**] |  | defaults to undefined|
| **deploymentId** | [**string**] |  | defaults to undefined|


### Return type

**StartImpersonationResponse**

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
|**201** | Created. |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **tailDeploymentLogs**
> string tailDeploymentLogs()


### Example

```typescript
import {
    DeploymentsApi,
    Configuration
} from '@omarss/saas-controlplane-sdk';

const configuration = new Configuration();
const apiInstance = new DeploymentsApi(configuration);

let deploymentId: string; // (default to undefined)
let since: string; // (optional) (default to undefined)
let filter: string; // (optional) (default to undefined)
let tail: number; // (optional) (default to 100)

const { status, data } = await apiInstance.tailDeploymentLogs(
    deploymentId,
    since,
    filter,
    tail
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **deploymentId** | [**string**] |  | defaults to undefined|
| **since** | [**string**] |  | (optional) defaults to undefined|
| **filter** | [**string**] |  | (optional) defaults to undefined|
| **tail** | [**number**] |  | (optional) defaults to 100|


### Return type

**string**

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/x-ndjson


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
|**200** | NDJSON log stream. |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **updateDeployment**
> DeploymentResponse updateDeployment(updateDeploymentRequest)


### Example

```typescript
import {
    DeploymentsApi,
    Configuration,
    UpdateDeploymentRequest
} from '@omarss/saas-controlplane-sdk';

const configuration = new Configuration();
const apiInstance = new DeploymentsApi(configuration);

let ifMatch: string; // (default to undefined)
let deploymentId: string; // (default to undefined)
let updateDeploymentRequest: UpdateDeploymentRequest; //
let idempotencyKey: string; // (optional) (default to undefined)

const { status, data } = await apiInstance.updateDeployment(
    ifMatch,
    deploymentId,
    updateDeploymentRequest,
    idempotencyKey
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **updateDeploymentRequest** | **UpdateDeploymentRequest**|  | |
| **ifMatch** | [**string**] |  | defaults to undefined|
| **deploymentId** | [**string**] |  | defaults to undefined|
| **idempotencyKey** | [**string**] |  | (optional) defaults to undefined|


### Return type

**DeploymentResponse**

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
|**200** | OK |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **upgradeDeployment**
> DeploymentResponse upgradeDeployment(upgradeDeploymentRequest)


### Example

```typescript
import {
    DeploymentsApi,
    Configuration,
    UpgradeDeploymentRequest
} from '@omarss/saas-controlplane-sdk';

const configuration = new Configuration();
const apiInstance = new DeploymentsApi(configuration);

let idempotencyKey: string; // (default to undefined)
let deploymentId: string; // (default to undefined)
let upgradeDeploymentRequest: UpgradeDeploymentRequest; //

const { status, data } = await apiInstance.upgradeDeployment(
    idempotencyKey,
    deploymentId,
    upgradeDeploymentRequest
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **upgradeDeploymentRequest** | **UpgradeDeploymentRequest**|  | |
| **idempotencyKey** | [**string**] |  | defaults to undefined|
| **deploymentId** | [**string**] |  | defaults to undefined|


### Return type

**DeploymentResponse**

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
|**202** | Accepted |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

