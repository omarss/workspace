# SendNotificationRequest


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**workflow_name** | **string** |  | [default to undefined]
**to** | [**SendNotificationRequestTo**](SendNotificationRequestTo.md) |  | [default to undefined]
**payload** | **{ [key: string]: any; }** |  | [optional] [default to undefined]

## Example

```typescript
import { SendNotificationRequest } from '@omarss/saas-dataplane-sdk';

const instance: SendNotificationRequest = {
    workflow_name,
    to,
    payload,
};
```

[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
