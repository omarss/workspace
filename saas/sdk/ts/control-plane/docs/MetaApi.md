# MetaApi

All URIs are relative to *https://control.saas.omarss.net*

|Method | HTTP request | Description|
|------------- | ------------- | -------------|
|[**getHealthz**](#gethealthz) | **GET** /healthz | Liveness probe.|

# **getHealthz**
> Health getHealthz()

Returns 200 with a small status payload when the control plane is alive.

### Example

```typescript
import {
    MetaApi,
    Configuration
} from '@omarss/saas-controlplane-sdk';

const configuration = new Configuration();
const apiInstance = new MetaApi(configuration);

const { status, data } = await apiInstance.getHealthz();
```

### Parameters
This endpoint does not have any parameters.


### Return type

**Health**

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

