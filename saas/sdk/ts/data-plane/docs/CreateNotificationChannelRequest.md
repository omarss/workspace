# CreateNotificationChannelRequest


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**provider** | **string** |  | [default to undefined]
**name** | **string** |  | [default to undefined]
**config** | **{ [key: string]: string; }** |  | [optional] [default to undefined]
**is_default_for** | **Array&lt;string&gt;** |  | [optional] [default to undefined]
**credentials** | [**CredentialsBundle**](CredentialsBundle.md) |  | [optional] [default to undefined]

## Example

```typescript
import { CreateNotificationChannelRequest } from '@omarss/saas-dataplane-sdk';

const instance: CreateNotificationChannelRequest = {
    provider,
    name,
    config,
    is_default_for,
    credentials,
};
```

[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
