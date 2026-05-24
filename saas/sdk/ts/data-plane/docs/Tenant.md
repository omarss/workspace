# Tenant


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **string** |  | [default to undefined]
**object** | **string** |  | [default to undefined]
**slug** | **string** |  | [default to undefined]
**name** | **string** |  | [default to undefined]
**status** | **string** |  | [default to undefined]
**default_organization_id** | **string** |  | [optional] [default to undefined]
**metadata** | **{ [key: string]: string; }** |  | [optional] [default to undefined]
**created_at** | **string** |  | [default to undefined]
**updated_at** | **string** |  | [default to undefined]
**deleted_at** | **string** |  | [optional] [default to undefined]
**etag** | **string** | Weak ETag, format W/\&quot;v&lt;sequence&gt;\&quot;. | [default to undefined]

## Example

```typescript
import { Tenant } from '@omarss/saas-dataplane-sdk';

const instance: Tenant = {
    id,
    object,
    slug,
    name,
    status,
    default_organization_id,
    metadata,
    created_at,
    updated_at,
    deleted_at,
    etag,
};
```

[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
