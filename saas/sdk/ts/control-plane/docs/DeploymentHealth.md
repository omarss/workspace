# DeploymentHealth


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**deployment_id** | **string** |  | [optional] [default to undefined]
**overall** | **string** |  | [optional] [default to undefined]
**components** | [**Array&lt;DeploymentHealthComponentsInner&gt;**](DeploymentHealthComponentsInner.md) |  | [optional] [default to undefined]
**checked_at** | **string** |  | [optional] [default to undefined]

## Example

```typescript
import { DeploymentHealth } from '@omarss/saas-controlplane-sdk';

const instance: DeploymentHealth = {
    deployment_id,
    overall,
    components,
    checked_at,
};
```

[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
