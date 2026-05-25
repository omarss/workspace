# ControlPlaneAuditEvent


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **string** |  | [optional] [default to undefined]
**operator_id** | **string** |  | [optional] [default to undefined]
**action** | **string** |  | [optional] [default to undefined]
**deployment_id** | **string** |  | [optional] [default to undefined]
**resource_type** | **string** |  | [optional] [default to undefined]
**resource_id** | **string** |  | [optional] [default to undefined]
**occurred_at** | **string** |  | [optional] [default to undefined]
**ip_address** | **string** |  | [optional] [default to undefined]
**request_id** | **string** |  | [optional] [default to undefined]
**metadata** | **{ [key: string]: any; }** |  | [optional] [default to undefined]

## Example

```typescript
import { ControlPlaneAuditEvent } from '@omarss/saas-controlplane-sdk';

const instance: ControlPlaneAuditEvent = {
    id,
    operator_id,
    action,
    deployment_id,
    resource_type,
    resource_id,
    occurred_at,
    ip_address,
    request_id,
    metadata,
};
```

[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
