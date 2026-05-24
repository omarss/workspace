# Problem


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **string** |  | [default to undefined]
**title** | **string** |  | [default to undefined]
**status** | **number** |  | [default to undefined]
**detail** | **string** |  | [optional] [default to undefined]
**instance** | **string** |  | [optional] [default to undefined]
**request_id** | **string** |  | [optional] [default to undefined]
**errors** | [**Array&lt;FieldError&gt;**](FieldError.md) |  | [optional] [default to undefined]

## Example

```typescript
import { Problem } from '@omarss/saas-dataplane-sdk';

const instance: Problem = {
    type,
    title,
    status,
    detail,
    instance,
    request_id,
    errors,
};
```

[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
