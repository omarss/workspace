# DeploymentDomain


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **string** |  | [default to undefined]
**deployment_id** | **string** |  | [default to undefined]
**domain** | **string** |  | [default to undefined]
**is_primary** | **boolean** |  | [optional] [default to undefined]
**status** | **string** |  | [default to undefined]
**verification_method** | **string** |  | [default to undefined]
**verification_record** | [**DeploymentDomainVerificationRecord**](DeploymentDomainVerificationRecord.md) |  | [default to undefined]
**verified_at** | **string** |  | [optional] [default to undefined]
**last_check_at** | **string** |  | [optional] [default to undefined]
**last_check_error** | **string** |  | [optional] [default to undefined]
**cert_status** | **string** |  | [optional] [default to undefined]
**created_at** | **string** |  | [default to undefined]

## Example

```typescript
import { DeploymentDomain } from '@omarss/saas-controlplane-sdk';

const instance: DeploymentDomain = {
    id,
    deployment_id,
    domain,
    is_primary,
    status,
    verification_method,
    verification_record,
    verified_at,
    last_check_at,
    last_check_error,
    cert_status,
    created_at,
};
```

[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
