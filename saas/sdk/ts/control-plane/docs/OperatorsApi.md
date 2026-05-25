# OperatorsApi

All URIs are relative to *https://control.saas.omarss.net*

|Method | HTTP request | Description|
|------------- | ------------- | -------------|
|[**listOperators**](#listoperators) | **GET** /control/v1/operators | List operators (Phase 13 extends with MFA status).|

# **listOperators**
> OperatorListResponse listOperators()


### Example

```typescript
import {
    OperatorsApi,
    Configuration
} from '@omarss/saas-controlplane-sdk';

const configuration = new Configuration();
const apiInstance = new OperatorsApi(configuration);

const { status, data } = await apiInstance.listOperators();
```

### Parameters
This endpoint does not have any parameters.


### Return type

**OperatorListResponse**

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

