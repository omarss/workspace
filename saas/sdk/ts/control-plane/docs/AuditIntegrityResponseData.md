# AuditIntegrityResponseData


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**verified** | **boolean** |  | [default to undefined]
**rows_checked** | **number** |  | [default to undefined]
**tenants_checked** | **number** |  | [default to undefined]
**first_mismatch_id** | **string** |  | [optional] [default to undefined]
**first_mismatch_tenant_id** | **string** |  | [optional] [default to undefined]
**first_mismatch_sequence** | **number** |  | [optional] [default to undefined]
**first_mismatch_reason** | **string** |  | [optional] [default to undefined]
**verified_at** | **string** |  | [default to undefined]

## Example

```typescript
import { AuditIntegrityResponseData } from '@omarss/saas-controlplane-sdk';

const instance: AuditIntegrityResponseData = {
    verified,
    rows_checked,
    tenants_checked,
    first_mismatch_id,
    first_mismatch_tenant_id,
    first_mismatch_sequence,
    first_mismatch_reason,
    verified_at,
};
```

[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
