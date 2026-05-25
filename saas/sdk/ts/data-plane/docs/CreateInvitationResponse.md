# CreateInvitationResponse


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**data** | [**Invitation**](Invitation.md) |  | [default to undefined]
**accept_url** | **string** | Full accept URL including the one-time plaintext token. Never logged; returned only in this 202 response. | [default to undefined]
**state** | **string** | Plaintext one-time accept token. Discard after sending the email; subsequent reads return only token_prefix. | [default to undefined]
**expires_at** | **string** |  | [default to undefined]

## Example

```typescript
import { CreateInvitationResponse } from '@omarss/saas-dataplane-sdk';

const instance: CreateInvitationResponse = {
    data,
    accept_url,
    state,
    expires_at,
};
```

[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
