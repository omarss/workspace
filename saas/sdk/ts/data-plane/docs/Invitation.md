# Invitation


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **string** |  | [default to undefined]
**object** | **string** |  | [default to undefined]
**tenant_id** | **string** |  | [default to undefined]
**organization_id** | **string** |  | [default to undefined]
**invitee_email** | **string** |  | [default to undefined]
**token_prefix** | **string** | First 8 chars of the base64-url accept token. The full token is only returned in the POST /invitations 202 response. | [default to undefined]
**invited_by_user_id** | **string** |  | [optional] [default to undefined]
**proposed_role_id** | **string** |  | [optional] [default to undefined]
**status** | **string** |  | [default to undefined]
**expires_at** | **string** |  | [default to undefined]
**accepted_at** | **string** |  | [optional] [default to undefined]
**accepted_by_user_id** | **string** |  | [optional] [default to undefined]
**revoked_at** | **string** |  | [optional] [default to undefined]
**revoked_by_user_id** | **string** |  | [optional] [default to undefined]
**created_at** | **string** |  | [default to undefined]
**updated_at** | **string** |  | [default to undefined]
**etag** | **string** |  | [default to undefined]

## Example

```typescript
import { Invitation } from '@omarss/saas-dataplane-sdk';

const instance: Invitation = {
    id,
    object,
    tenant_id,
    organization_id,
    invitee_email,
    token_prefix,
    invited_by_user_id,
    proposed_role_id,
    status,
    expires_at,
    accepted_at,
    accepted_by_user_id,
    revoked_at,
    revoked_by_user_id,
    created_at,
    updated_at,
    etag,
};
```

[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
