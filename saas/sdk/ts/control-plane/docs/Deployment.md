# Deployment


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **string** |  | [default to undefined]
**project_slug** | **string** |  | [default to undefined]
**environment_slug** | **string** |  | [default to undefined]
**region** | **string** |  | [optional] [default to undefined]
**modules** | **Array&lt;string&gt;** |  | [optional] [default to undefined]
**image_version** | **string** |  | [default to undefined]
**data_residency** | **string** |  | [optional] [default to undefined]
**primary_vhost** | **string** |  | [default to undefined]
**custom_domains** | **Array&lt;string&gt;** |  | [optional] [default to undefined]
**status** | **string** |  | [default to undefined]
**metadata** | **{ [key: string]: string; }** |  | [optional] [default to undefined]
**last_event_id** | **string** |  | [optional] [default to undefined]
**retain_until** | **string** |  | [optional] [default to undefined]
**created_at** | **string** |  | [default to undefined]
**updated_at** | **string** |  | [optional] [default to undefined]
**etag** | **string** |  | [optional] [default to undefined]

## Example

```typescript
import { Deployment } from '@omarss/saas-controlplane-sdk';

const instance: Deployment = {
    id,
    project_slug,
    environment_slug,
    region,
    modules,
    image_version,
    data_residency,
    primary_vhost,
    custom_domains,
    status,
    metadata,
    last_event_id,
    retain_until,
    created_at,
    updated_at,
    etag,
};
```

[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
