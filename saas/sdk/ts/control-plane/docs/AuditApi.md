# AuditApi

All URIs are relative to *https://control.saas.omarss.net*

|Method | HTTP request | Description|
|------------- | ------------- | -------------|
|[**verifyDeploymentAuditIntegrity**](#verifydeploymentauditintegrity) | **GET** /control/v1/deployments/{deployment_id}/audit-integrity | Walk the audit chain and report the first mismatch (if any).|

# **verifyDeploymentAuditIntegrity**
> AuditIntegrityResponse verifyDeploymentAuditIntegrity()

Operator-only. The chain walk is in-order per tenant; the result terminates at the first mismatch. Reasons: sequence-gap, prev_hash, row_hash. For very large deployments this endpoint is long-running; the v1 roadmap moves it onto a background job. Phase 10 ships the synchronous shape. 

### Example

```typescript
import {
    AuditApi,
    Configuration
} from '@omarss/saas-controlplane-sdk';

const configuration = new Configuration();
const apiInstance = new AuditApi(configuration);

let deploymentId: string; // (default to undefined)
let tenantId: string; //Optional — verify a single tenant\'s chain instead of every tenant on the Deployment. (optional) (default to undefined)

const { status, data } = await apiInstance.verifyDeploymentAuditIntegrity(
    deploymentId,
    tenantId
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **deploymentId** | [**string**] |  | defaults to undefined|
| **tenantId** | [**string**] | Optional — verify a single tenant\&#39;s chain instead of every tenant on the Deployment. | (optional) defaults to undefined|


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

