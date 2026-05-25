# AuditEvent


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **string** |  | [default to undefined]
**tenant_id** | **string** |  | [default to undefined]
**actor_type** | **string** |  | [default to undefined]
**actor_id** | **string** |  | [default to undefined]
**action** | **string** |  | [default to undefined]
**resource_type** | **string** |  | [default to undefined]
**resource_id** | **string** |  | [optional] [default to undefined]
**occurred_at** | **string** |  | [default to undefined]
**ip_address** | **string** |  | [optional] [default to undefined]
**user_agent** | **string** |  | [optional] [default to undefined]
**request_id** | **string** |  | [optional] [default to undefined]
**metadata** | **{ [key: string]: any; }** |  | [optional] [default to undefined]
**prev_hash** | **string** | Lowercase hex SHA-256 of the previous row, or the per-tenant Genesis seed for chain_sequence&#x3D;1. | [default to undefined]
**row_hash** | **string** | Lowercase hex SHA-256 of (prev_hash || JCS(canonical row body)). | [default to undefined]
**chain_sequence** | **number** | Per-tenant monotonic sequence number starting at 1. | [default to undefined]

## Example

```typescript
import { AuditEvent } from '@omarss/saas-dataplane-sdk';

const instance: AuditEvent = {
    id,
    tenant_id,
    actor_type,
    actor_id,
    action,
    resource_type,
    resource_id,
    occurred_at,
    ip_address,
    user_agent,
    request_id,
    metadata,
    prev_hash,
    row_hash,
    chain_sequence,
};
```

[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
