# StartImpersonationRequest


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**target_member_id** | **string** |  | [default to undefined]
**reason** | **string** |  | [default to undefined]
**duration_seconds** | **number** |  | [optional] [default to 900]

## Example

```typescript
import { StartImpersonationRequest } from '@omarss/saas-controlplane-sdk';

const instance: StartImpersonationRequest = {
    target_member_id,
    reason,
    duration_seconds,
};
```

[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
