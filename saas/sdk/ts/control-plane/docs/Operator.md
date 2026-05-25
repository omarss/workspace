# Operator


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **string** |  | [optional] [default to undefined]
**email** | **string** |  | [optional] [default to undefined]
**name** | **string** |  | [optional] [default to undefined]
**is_active** | **boolean** |  | [optional] [default to undefined]
**mfa_enabled** | **boolean** |  | [optional] [default to undefined]
**ip_allowlist** | **Array&lt;string&gt;** |  | [optional] [default to undefined]

## Example

```typescript
import { Operator } from '@omarss/saas-controlplane-sdk';

const instance: Operator = {
    id,
    email,
    name,
    is_active,
    mfa_enabled,
    ip_allowlist,
};
```

[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
