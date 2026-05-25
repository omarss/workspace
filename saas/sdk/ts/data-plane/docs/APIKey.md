# APIKey


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **string** |  | [default to undefined]
**object** | **string** |  | [default to undefined]
**tenant_id** | **string** |  | [default to undefined]
**environment_id** | **string** |  | [optional] [default to undefined]
**name** | **string** |  | [default to undefined]
**prefix** | **string** | Visible prefix shape &#x60;&lt;env&gt;_&lt;8-char-random&gt;&#x60;, e.g. \&quot;live_AX9BC7D3\&quot;. | [default to undefined]
**scopes** | **Array&lt;string&gt;** |  | [default to undefined]
**status** | **string** |  | [default to undefined]
**rate_limit_per_minute** | **number** |  | [optional] [default to undefined]
**ip_allowlist** | **Array&lt;string&gt;** |  | [optional] [default to undefined]
**created_by** | **string** |  | [default to undefined]
**created_at** | **string** |  | [default to undefined]
**updated_at** | **string** |  | [default to undefined]
**expires_at** | **string** |  | [optional] [default to undefined]
**last_used_at** | **string** |  | [optional] [default to undefined]
**revoked_at** | **string** |  | [optional] [default to undefined]
**rotated_at** | **string** |  | [optional] [default to undefined]
**predecessor_expires_at** | **string** | When the previous secret stops authenticating during rotation grace. | [optional] [default to undefined]
**etag** | **string** | Weak ETag, format W/\&quot;v&lt;sequence&gt;\&quot;. | [default to undefined]

## Example

```typescript
import { APIKey } from '@omarss/saas-dataplane-sdk';

const instance: APIKey = {
    id,
    object,
    tenant_id,
    environment_id,
    name,
    prefix,
    scopes,
    status,
    rate_limit_per_minute,
    ip_allowlist,
    created_by,
    created_at,
    updated_at,
    expires_at,
    last_used_at,
    revoked_at,
    rotated_at,
    predecessor_expires_at,
    etag,
};
```

[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
