# Notification


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **string** |  | [default to undefined]
**object** | **string** |  | [default to undefined]
**tenant_id** | **string** |  | [default to undefined]
**workflow_name** | **string** |  | [default to undefined]
**to_user_id** | **string** |  | [default to undefined]
**status** | **string** |  | [default to undefined]
**novu_transaction_id** | **string** |  | [optional] [default to undefined]
**queued_at** | **string** |  | [default to undefined]
**sent_at** | **string** |  | [optional] [default to undefined]
**delivered_at** | **string** |  | [optional] [default to undefined]
**failed_at** | **string** |  | [optional] [default to undefined]
**failure_reason** | **string** |  | [optional] [default to undefined]

## Example

```typescript
import { Notification } from '@omarss/saas-dataplane-sdk';

const instance: Notification = {
    id,
    object,
    tenant_id,
    workflow_name,
    to_user_id,
    status,
    novu_transaction_id,
    queued_at,
    sent_at,
    delivered_at,
    failed_at,
    failure_reason,
};
```

[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
