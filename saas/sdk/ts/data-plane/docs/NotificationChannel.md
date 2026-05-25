# NotificationChannel


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **string** |  | [default to undefined]
**object** | **string** |  | [default to undefined]
**provider** | **string** |  | [default to undefined]
**name** | **string** |  | [default to undefined]
**status** | **string** |  | [default to undefined]
**is_default_for** | **Array&lt;string&gt;** |  | [optional] [default to undefined]
**config** | **{ [key: string]: string; }** |  | [optional] [default to undefined]
**credentials_present** | **boolean** | True iff the channel row currently carries envelope-encrypted credentials. The platform NEVER returns the credential bytes.  | [default to undefined]
**last_rotated_at** | **string** |  | [optional] [default to undefined]
**created_at** | **string** |  | [default to undefined]
**updated_at** | **string** |  | [default to undefined]
**etag** | **string** |  | [default to undefined]

## Example

```typescript
import { NotificationChannel } from '@omarss/saas-dataplane-sdk';

const instance: NotificationChannel = {
    id,
    object,
    provider,
    name,
    status,
    is_default_for,
    config,
    credentials_present,
    last_rotated_at,
    created_at,
    updated_at,
    etag,
};
```

[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
