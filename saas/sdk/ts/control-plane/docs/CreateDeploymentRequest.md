# CreateDeploymentRequest


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**project_slug** | **string** |  | [default to undefined]
**environment_slug** | **string** |  | [default to undefined]
**region** | **string** |  | [optional] [default to undefined]
**modules** | **Array&lt;string&gt;** |  | [optional] [default to undefined]
**image_version** | **string** |  | [default to undefined]
**data_residency** | **string** |  | [optional] [default to undefined]
**metadata** | **{ [key: string]: string; }** |  | [optional] [default to undefined]

## Example

```typescript
import { CreateDeploymentRequest } from '@omarss/saas-controlplane-sdk';

const instance: CreateDeploymentRequest = {
    project_slug,
    environment_slug,
    region,
    modules,
    image_version,
    data_residency,
    metadata,
};
```

[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
