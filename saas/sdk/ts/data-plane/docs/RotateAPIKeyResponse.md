# RotateAPIKeyResponse


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**data** | [**APIKey**](APIKey.md) |  | [default to undefined]
**secret** | **string** | New plaintext bearer; returned ONCE on rotate. | [default to undefined]
**predecessor_expires_at** | **string** | When the previous secret stops authenticating. | [default to undefined]

## Example

```typescript
import { RotateAPIKeyResponse } from '@omarss/saas-dataplane-sdk';

const instance: RotateAPIKeyResponse = {
    data,
    secret,
    predecessor_expires_at,
};
```

[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
