# AuthorizationApi

All URIs are relative to *https://dev.example.saas.omarss.net*

|Method | HTTP request | Description|
|------------- | ------------- | -------------|
|[**assignMemberRole**](#assignmemberrole) | **POST** /v1/members/{member_id}/roles | Assign a role to a member.|
|[**batchCheckAuthorization**](#batchcheckauthorization) | **POST** /v1/authorization/batch-check | Evaluate many checks in one call (max 100).|
|[**checkAuthorization**](#checkauthorization) | **POST** /v1/authorization/check | Evaluate a single (member, permission, tenant) check.|
|[**createRole**](#createrole) | **POST** /v1/tenants/{tenant_id}/roles | Create a new role in a tenant.|
|[**deleteRole**](#deleterole) | **DELETE** /v1/roles/{role_id} | Delete a role. System roles refuse delete with 422.|
|[**getRole**](#getrole) | **GET** /v1/roles/{role_id} | Fetch a role by id.|
|[**listMemberRoles**](#listmemberroles) | **GET** /v1/members/{member_id}/roles | List roles assigned to a member.|
|[**listPermissions**](#listpermissions) | **GET** /v1/permissions | List the deployment-wide permission catalogue.|
|[**listRoles**](#listroles) | **GET** /v1/tenants/{tenant_id}/roles | List roles in a tenant.|
|[**unassignMemberRole**](#unassignmemberrole) | **DELETE** /v1/members/{member_id}/roles/{role_id} | Unassign a role from a member.|
|[**updateRole**](#updaterole) | **PATCH** /v1/roles/{role_id} | Update a role. Permissions slice is set-replace.|

# **assignMemberRole**
> MemberRoleResponse assignMemberRole(assignMemberRoleRequest)


### Example

```typescript
import {
    AuthorizationApi,
    Configuration,
    AssignMemberRoleRequest
} from '@omarss/saas-dataplane-sdk';

const configuration = new Configuration();
const apiInstance = new AuthorizationApi(configuration);

let idempotencyKey: string; //24-hour idempotency key (idem_<ulid>). (default to undefined)
let memberId: string; // (default to undefined)
let assignMemberRoleRequest: AssignMemberRoleRequest; //

const { status, data } = await apiInstance.assignMemberRole(
    idempotencyKey,
    memberId,
    assignMemberRoleRequest
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **assignMemberRoleRequest** | **AssignMemberRoleRequest**|  | |
| **idempotencyKey** | [**string**] | 24-hour idempotency key (idem_&lt;ulid&gt;). | defaults to undefined|
| **memberId** | [**string**] |  | defaults to undefined|


### Return type

**MemberRoleResponse**

### Authorization

[apiKeyAuth](../README.md#apiKeyAuth), [bearerAuth](../README.md#bearerAuth)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json, application/problem+json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
|**200** | Assigned |  -  |
|**401** | Missing or invalid bearer token / API key. |  -  |
|**403** | Caller lacks permission for this resource. |  -  |
|**404** | Resource not found. |  -  |
|**422** | Idempotency-Key reused with a different body, OR validation failed. |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **batchCheckAuthorization**
> BatchCheckAuthorizationResponse batchCheckAuthorization(batchCheckAuthorizationRequest)


### Example

```typescript
import {
    AuthorizationApi,
    Configuration,
    BatchCheckAuthorizationRequest
} from '@omarss/saas-dataplane-sdk';

const configuration = new Configuration();
const apiInstance = new AuthorizationApi(configuration);

let batchCheckAuthorizationRequest: BatchCheckAuthorizationRequest; //

const { status, data } = await apiInstance.batchCheckAuthorization(
    batchCheckAuthorizationRequest
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **batchCheckAuthorizationRequest** | **BatchCheckAuthorizationRequest**|  | |


### Return type

**BatchCheckAuthorizationResponse**

### Authorization

[apiKeyAuth](../README.md#apiKeyAuth), [bearerAuth](../README.md#bearerAuth)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json, application/problem+json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
|**200** | OK |  -  |
|**401** | Missing or invalid bearer token / API key. |  -  |
|**403** | Caller lacks permission for this resource. |  -  |
|**422** | Idempotency-Key reused with a different body, OR validation failed. |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **checkAuthorization**
> CheckAuthorizationResponse checkAuthorization(checkAuthorizationRequest)

Synchronous policy check. Returns `allowed=true` plus the role that matched, or `allowed=false`. Denied checks emit an `authorization.denied` outbox event so the audit log records the attempt. 

### Example

```typescript
import {
    AuthorizationApi,
    Configuration,
    CheckAuthorizationRequest
} from '@omarss/saas-dataplane-sdk';

const configuration = new Configuration();
const apiInstance = new AuthorizationApi(configuration);

let checkAuthorizationRequest: CheckAuthorizationRequest; //

const { status, data } = await apiInstance.checkAuthorization(
    checkAuthorizationRequest
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **checkAuthorizationRequest** | **CheckAuthorizationRequest**|  | |


### Return type

**CheckAuthorizationResponse**

### Authorization

[apiKeyAuth](../README.md#apiKeyAuth), [bearerAuth](../README.md#bearerAuth)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json, application/problem+json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
|**200** | OK |  -  |
|**401** | Missing or invalid bearer token / API key. |  -  |
|**403** | Caller lacks permission for this resource. |  -  |
|**422** | Idempotency-Key reused with a different body, OR validation failed. |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **createRole**
> RoleResponse createRole(createRoleRequest)

Roles are tenant-scoped. The optional `permissions` array seeds the role\'s p-rows in a single transaction. Permission ids must exist in the deployment-wide catalogue (`/v1/permissions`). 

### Example

```typescript
import {
    AuthorizationApi,
    Configuration,
    CreateRoleRequest
} from '@omarss/saas-dataplane-sdk';

const configuration = new Configuration();
const apiInstance = new AuthorizationApi(configuration);

let idempotencyKey: string; //24-hour idempotency key (idem_<ulid>). (default to undefined)
let tenantId: string; // (default to undefined)
let createRoleRequest: CreateRoleRequest; //

const { status, data } = await apiInstance.createRole(
    idempotencyKey,
    tenantId,
    createRoleRequest
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **createRoleRequest** | **CreateRoleRequest**|  | |
| **idempotencyKey** | [**string**] | 24-hour idempotency key (idem_&lt;ulid&gt;). | defaults to undefined|
| **tenantId** | [**string**] |  | defaults to undefined|


### Return type

**RoleResponse**

### Authorization

[apiKeyAuth](../README.md#apiKeyAuth), [bearerAuth](../README.md#bearerAuth)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json, application/problem+json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
|**201** | Created |  * ETag -  <br>  * Location -  <br>  |
|**401** | Missing or invalid bearer token / API key. |  -  |
|**403** | Caller lacks permission for this resource. |  -  |
|**422** | Idempotency-Key reused with a different body, OR validation failed. |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **deleteRole**
> deleteRole()


### Example

```typescript
import {
    AuthorizationApi,
    Configuration
} from '@omarss/saas-dataplane-sdk';

const configuration = new Configuration();
const apiInstance = new AuthorizationApi(configuration);

let ifMatch: string; //Weak ETag from a prior GET; rejects on mismatch with 412. (default to undefined)
let roleId: string; // (default to undefined)

const { status, data } = await apiInstance.deleteRole(
    ifMatch,
    roleId
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **ifMatch** | [**string**] | Weak ETag from a prior GET; rejects on mismatch with 412. | defaults to undefined|
| **roleId** | [**string**] |  | defaults to undefined|


### Return type

void (empty response body)

### Authorization

[apiKeyAuth](../README.md#apiKeyAuth), [bearerAuth](../README.md#bearerAuth)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/problem+json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
|**204** | Deleted |  -  |
|**401** | Missing or invalid bearer token / API key. |  -  |
|**403** | Caller lacks permission for this resource. |  -  |
|**404** | Resource not found. |  -  |
|**412** | If-Match header missing or stale. |  -  |
|**422** | Role is system-protected. |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **getRole**
> RoleResponse getRole()


### Example

```typescript
import {
    AuthorizationApi,
    Configuration
} from '@omarss/saas-dataplane-sdk';

const configuration = new Configuration();
const apiInstance = new AuthorizationApi(configuration);

let roleId: string; // (default to undefined)

const { status, data } = await apiInstance.getRole(
    roleId
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **roleId** | [**string**] |  | defaults to undefined|


### Return type

**RoleResponse**

### Authorization

[apiKeyAuth](../README.md#apiKeyAuth), [bearerAuth](../README.md#bearerAuth)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json, application/problem+json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
|**200** | OK |  -  |
|**401** | Missing or invalid bearer token / API key. |  -  |
|**403** | Caller lacks permission for this resource. |  -  |
|**404** | Resource not found. |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **listMemberRoles**
> MemberRoleListResponse listMemberRoles()


### Example

```typescript
import {
    AuthorizationApi,
    Configuration
} from '@omarss/saas-dataplane-sdk';

const configuration = new Configuration();
const apiInstance = new AuthorizationApi(configuration);

let memberId: string; // (default to undefined)

const { status, data } = await apiInstance.listMemberRoles(
    memberId
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **memberId** | [**string**] |  | defaults to undefined|


### Return type

**MemberRoleListResponse**

### Authorization

[apiKeyAuth](../README.md#apiKeyAuth), [bearerAuth](../README.md#bearerAuth)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json, application/problem+json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
|**200** | OK |  -  |
|**401** | Missing or invalid bearer token / API key. |  -  |
|**403** | Caller lacks permission for this resource. |  -  |
|**404** | Resource not found. |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **listPermissions**
> PermissionListResponse listPermissions()


### Example

```typescript
import {
    AuthorizationApi,
    Configuration
} from '@omarss/saas-dataplane-sdk';

const configuration = new Configuration();
const apiInstance = new AuthorizationApi(configuration);

const { status, data } = await apiInstance.listPermissions();
```

### Parameters
This endpoint does not have any parameters.


### Return type

**PermissionListResponse**

### Authorization

[apiKeyAuth](../README.md#apiKeyAuth), [bearerAuth](../README.md#bearerAuth)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json, application/problem+json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
|**200** | OK |  -  |
|**401** | Missing or invalid bearer token / API key. |  -  |
|**403** | Caller lacks permission for this resource. |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **listRoles**
> RoleListResponse listRoles()


### Example

```typescript
import {
    AuthorizationApi,
    Configuration
} from '@omarss/saas-dataplane-sdk';

const configuration = new Configuration();
const apiInstance = new AuthorizationApi(configuration);

let tenantId: string; // (default to undefined)
let limit: number; //Max items to return (default 25, max 200). (optional) (default to 25)

const { status, data } = await apiInstance.listRoles(
    tenantId,
    limit
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **tenantId** | [**string**] |  | defaults to undefined|
| **limit** | [**number**] | Max items to return (default 25, max 200). | (optional) defaults to 25|


### Return type

**RoleListResponse**

### Authorization

[apiKeyAuth](../README.md#apiKeyAuth), [bearerAuth](../README.md#bearerAuth)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json, application/problem+json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
|**200** | OK |  -  |
|**401** | Missing or invalid bearer token / API key. |  -  |
|**403** | Caller lacks permission for this resource. |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **unassignMemberRole**
> unassignMemberRole()


### Example

```typescript
import {
    AuthorizationApi,
    Configuration
} from '@omarss/saas-dataplane-sdk';

const configuration = new Configuration();
const apiInstance = new AuthorizationApi(configuration);

let memberId: string; // (default to undefined)
let roleId: string; // (default to undefined)

const { status, data } = await apiInstance.unassignMemberRole(
    memberId,
    roleId
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **memberId** | [**string**] |  | defaults to undefined|
| **roleId** | [**string**] |  | defaults to undefined|


### Return type

void (empty response body)

### Authorization

[apiKeyAuth](../README.md#apiKeyAuth), [bearerAuth](../README.md#bearerAuth)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/problem+json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
|**204** | Unassigned |  -  |
|**401** | Missing or invalid bearer token / API key. |  -  |
|**403** | Caller lacks permission for this resource. |  -  |
|**404** | Resource not found. |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **updateRole**
> RoleResponse updateRole(updateRoleRequest)


### Example

```typescript
import {
    AuthorizationApi,
    Configuration,
    UpdateRoleRequest
} from '@omarss/saas-dataplane-sdk';

const configuration = new Configuration();
const apiInstance = new AuthorizationApi(configuration);

let ifMatch: string; //Weak ETag from a prior GET; rejects on mismatch with 412. (default to undefined)
let idempotencyKey: string; //24-hour idempotency key (idem_<ulid>). (default to undefined)
let roleId: string; // (default to undefined)
let updateRoleRequest: UpdateRoleRequest; //

const { status, data } = await apiInstance.updateRole(
    ifMatch,
    idempotencyKey,
    roleId,
    updateRoleRequest
);
```

### Parameters

|Name | Type | Description  | Notes|
|------------- | ------------- | ------------- | -------------|
| **updateRoleRequest** | **UpdateRoleRequest**|  | |
| **ifMatch** | [**string**] | Weak ETag from a prior GET; rejects on mismatch with 412. | defaults to undefined|
| **idempotencyKey** | [**string**] | 24-hour idempotency key (idem_&lt;ulid&gt;). | defaults to undefined|
| **roleId** | [**string**] |  | defaults to undefined|


### Return type

**RoleResponse**

### Authorization

[apiKeyAuth](../README.md#apiKeyAuth), [bearerAuth](../README.md#bearerAuth)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json, application/problem+json


### HTTP response details
| Status code | Description | Response headers |
|-------------|-------------|------------------|
|**200** | OK |  * ETag -  <br>  |
|**401** | Missing or invalid bearer token / API key. |  -  |
|**403** | Caller lacks permission for this resource. |  -  |
|**404** | Resource not found. |  -  |
|**412** | If-Match header missing or stale. |  -  |
|**422** | Idempotency-Key reused with a different body, OR validation failed. |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

