# UpdateNotificationWorkflowRequest

Partial-update payload. Both fields are optional; omit a field to leave it unchanged. At least one MUST be provided. 

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**novu_workflow_id** | **string** |  | [optional] [default to undefined]
**description** | **string** |  | [optional] [default to undefined]

## Example

```typescript
import { UpdateNotificationWorkflowRequest } from '@omarss/saas-dataplane-sdk';

const instance: UpdateNotificationWorkflowRequest = {
    novu_workflow_id,
    description,
};
```

[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
