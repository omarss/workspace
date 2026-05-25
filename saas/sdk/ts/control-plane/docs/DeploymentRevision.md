# DeploymentRevision


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **string** |  | [optional] [default to undefined]
**deployment_id** | **string** |  | [optional] [default to undefined]
**image_version** | **string** |  | [optional] [default to undefined]
**applied_at** | **string** |  | [optional] [default to undefined]
**is_rolled_back** | **boolean** |  | [optional] [default to undefined]
**applied_by** | **string** |  | [optional] [default to undefined]

## Example

```typescript
import { DeploymentRevision } from '@omarss/saas-controlplane-sdk';

const instance: DeploymentRevision = {
    id,
    deployment_id,
    image_version,
    applied_at,
    is_rolled_back,
    applied_by,
};
```

[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
