# CreateAPIKeyResponse


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**data** | [**APIKey**](APIKey.md) |  | [default to undefined]
**secret** | **string** | Plaintext bearer; returned ONCE on create. Store immediately. | [default to undefined]

## Example

```typescript
import { CreateAPIKeyResponse } from '@omarss/saas-dataplane-sdk';

const instance: CreateAPIKeyResponse = {
    data,
    secret,
};
```

[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
