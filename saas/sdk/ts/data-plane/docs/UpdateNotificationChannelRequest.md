# UpdateNotificationChannelRequest


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**name** | **string** |  | [optional] [default to undefined]
**status** | **string** |  | [optional] [default to undefined]
**is_default_for** | **Array&lt;string&gt;** |  | [optional] [default to undefined]
**config** | **{ [key: string]: string; }** |  | [optional] [default to undefined]

## Example

```typescript
import { UpdateNotificationChannelRequest } from '@omarss/saas-dataplane-sdk';

const instance: UpdateNotificationChannelRequest = {
    name,
    status,
    is_default_for,
    config,
};
```

[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
