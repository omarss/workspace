# Member


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **string** |  | [default to undefined]
**object** | **string** |  | [default to undefined]
**tenant_id** | **string** |  | [default to undefined]
**organization_id** | **string** |  | [default to undefined]
**user_id** | **string** |  | [default to undefined]
**role_id** | **string** |  | [optional] [default to undefined]
**status** | **string** |  | [default to undefined]
**metadata** | **{ [key: string]: string; }** |  | [optional] [default to undefined]
**joined_at** | **string** |  | [default to undefined]
**updated_at** | **string** |  | [default to undefined]
**removed_at** | **string** |  | [optional] [default to undefined]
**etag** | **string** |  | [default to undefined]

## Example

```typescript
import { Member } from '@omarss/saas-dataplane-sdk';

const instance: Member = {
    id,
    object,
    tenant_id,
    organization_id,
    user_id,
    role_id,
    status,
    metadata,
    joined_at,
    updated_at,
    removed_at,
    etag,
};
```

[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
