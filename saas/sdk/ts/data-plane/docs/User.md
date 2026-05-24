# User


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **string** |  | [default to undefined]
**object** | **string** |  | [default to undefined]
**tenant_id** | **string** |  | [default to undefined]
**email** | **string** |  | [default to undefined]
**email_verified** | **boolean** |  | [default to undefined]
**name** | **string** |  | [optional] [default to undefined]
**phone** | **string** |  | [optional] [default to undefined]
**status** | **string** |  | [default to undefined]
**metadata** | **{ [key: string]: string; }** |  | [optional] [default to undefined]
**created_at** | **string** |  | [default to undefined]
**updated_at** | **string** |  | [default to undefined]
**etag** | **string** | Weak ETag, format W/\&quot;v&lt;sequence&gt;\&quot;. | [default to undefined]

## Example

```typescript
import { User } from '@omarss/saas-dataplane-sdk';

const instance: User = {
    id,
    object,
    tenant_id,
    email,
    email_verified,
    name,
    phone,
    status,
    metadata,
    created_at,
    updated_at,
    etag,
};
```

[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
