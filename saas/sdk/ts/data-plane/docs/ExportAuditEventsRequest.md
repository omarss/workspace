# ExportAuditEventsRequest


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**tenant_id** | **string** |  | [optional] [default to undefined]
**action** | **string** |  | [optional] [default to undefined]
**resource_type** | **string** |  | [optional] [default to undefined]
**resource_id** | **string** |  | [optional] [default to undefined]
**actor_id** | **string** |  | [optional] [default to undefined]
**occurred_after** | **string** |  | [optional] [default to undefined]
**occurred_before** | **string** |  | [optional] [default to undefined]
**format** | **string** |  | [optional] [default to FormatEnum_Json]
**limit** | **number** |  | [optional] [default to undefined]

## Example

```typescript
import { ExportAuditEventsRequest } from '@omarss/saas-dataplane-sdk';

const instance: ExportAuditEventsRequest = {
    tenant_id,
    action,
    resource_type,
    resource_id,
    actor_id,
    occurred_after,
    occurred_before,
    format,
    limit,
};
```

[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
