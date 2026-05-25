# UpdateAPIKeyRequest


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**name** | **string** |  | [optional] [default to undefined]
**scopes** | **Array&lt;string&gt;** |  | [optional] [default to undefined]
**rate_limit_per_minute** | **number** |  | [optional] [default to undefined]
**ip_allowlist** | **Array&lt;string&gt;** |  | [optional] [default to undefined]
**expires_at** | **string** |  | [optional] [default to undefined]

## Example

```typescript
import { UpdateAPIKeyRequest } from '@omarss/saas-dataplane-sdk';

const instance: UpdateAPIKeyRequest = {
    name,
    scopes,
    rate_limit_per_minute,
    ip_allowlist,
    expires_at,
};
```

[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
