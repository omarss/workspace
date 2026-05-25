# AuditApi

All URIs are relative to *https://control.saas.omarss.net*

|Method | HTTP request | Description|
|------------- | ------------- | -------------|
|[**listControlPlaneAuditEvents**](#listcontrolplaneauditevents) | **GET** /control/v1/audit-events | List control-plane operator audit events.|
|[**verifyDeploymentAuditIntegrity**](#verifydeploymentauditintegrity) | **GET** /control/v1/deployments/{deployment_id}/audit-integrity | Walk the audit chain and report the first mismatch (if any).|

# **listControlPlaneAuditEvents**
> ControlPlaneAuditEventListResponse listControlPlaneAuditEvents()


### Example

```typescript
import {
    AuditApi,
    Configuration
} from '@omarss/saas-controlplane-sdk';

const configuration = new Configuration();
const apiInstance = new AuditApi(configuration);

let limit: number; // (optional) (default to 25)
let cursor: string; // (optional) (default to undefined)
let deploymentId: string; // (optional) (default to undefined)
let operatorId: string; // (optional) (default to undefined)

const { status, data } = await apiInstance.listControlPlaneAuditEvents(
    limit,
    cursor,
    deploymentId,
    operatorId
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **limit** | [**number**] |  | (optional) defaults to 25|
| **cursor** | [**string**] |  | (optional) defaults to undefined|
| **deploymentId** | [**string**] |  | (optional) defaults to undefined|
| **operatorId** | [**string**] |  | (optional) defaults to undefined|


### Return type

**ControlPlaneAuditEventListResponse**

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

# **verifyDeploymentAuditIntegrity**
> AuditIntegrityResponse verifyDeploymentAuditIntegrity()


### Example

```typescript
import {
    AuditApi,
    Configuration
} from '@omarss/saas-controlplane-sdk';

const configuration = new Configuration();
const apiInstance = new AuditApi(configuration);

let deploymentId: string; // (default to undefined)
let tenantId: string; // (optional) (default to undefined)

const { status, data } = await apiInstance.verifyDeploymentAuditIntegrity(
    deploymentId,
    tenantId
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **deploymentId** | [**string**] |  | defaults to undefined|
| **tenantId** | [**string**] |  | (optional) defaults to undefined|


### Return type

**AuditIntegrityResponse**

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

