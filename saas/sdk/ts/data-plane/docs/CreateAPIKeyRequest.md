# CreateAPIKeyRequest


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**name** | **string** |  | [default to undefined]
**scopes** | **Array&lt;string&gt;** |  | [default to undefined]
**environment_id** | **string** |  | [optional] [default to undefined]
**expires_at** | **string** |  | [optional] [default to undefined]
**rate_limit_per_minute** | **number** |  | [optional] [default to undefined]
**ip_allowlist** | **Array&lt;string&gt;** |  | [optional] [default to undefined]

## Example

```typescript
import { CreateAPIKeyRequest } from '@omarss/saas-dataplane-sdk';

const instance: CreateAPIKeyRequest = {
    name,
    scopes,
    environment_id,
    expires_at,
    rate_limit_per_minute,
    ip_allowlist,
};
```

[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
