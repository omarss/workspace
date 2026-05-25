# Role


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **string** |  | [default to undefined]
**object** | **string** |  | [default to undefined]
**tenant_id** | **string** |  | [default to undefined]
**name** | **string** |  | [default to undefined]
**description** | **string** |  | [optional] [default to undefined]
**is_system** | **boolean** |  | [default to undefined]
**permissions** | **Array&lt;string&gt;** | Permission ids granted to this role. | [optional] [default to undefined]
**metadata** | **{ [key: string]: string; }** |  | [optional] [default to undefined]
**created_at** | **string** |  | [default to undefined]
**updated_at** | **string** |  | [default to undefined]
**etag** | **string** |  | [default to undefined]

## Example

```typescript
import { Role } from '@omarss/saas-dataplane-sdk';

const instance: Role = {
    id,
    object,
    tenant_id,
    name,
    description,
    is_system,
    permissions,
    metadata,
    created_at,
    updated_at,
    etag,
};
```

[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
