# CreateUserRequest


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**email** | **string** |  | [default to undefined]
**name** | **string** |  | [optional] [default to undefined]
**send_verification_email** | **boolean** |  | [optional] [default to true]
**metadata** | **{ [key: string]: string; }** |  | [optional] [default to undefined]

## Example

```typescript
import { CreateUserRequest } from '@omarss/saas-dataplane-sdk';

const instance: CreateUserRequest = {
    email,
    name,
    send_verification_email,
    metadata,
};
```

[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
