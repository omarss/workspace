## @omarss/saas-dataplane-sdk@0.0.2

This generator creates TypeScript/JavaScript client that utilizes [axios](https://github.com/axios/axios). The generated Node module can be used in the following environments:

Environment
* Node.js
* Webpack
* Browserify

Language level
* ES5 - you must have a Promises/A+ library installed
* ES6

Module system
* CommonJS
* ES6 module system

It can be used in both TypeScript and JavaScript. In TypeScript, the definition will be automatically resolved via `package.json`. ([Reference](https://www.typescriptlang.org/docs/handbook/declaration-files/consumption.html))

### Building

To build and compile the typescript sources to javascript use:
```
npm install
npm run build
```

### Publishing

First build the package then run `npm publish`

### Consuming

navigate to the folder of your consuming project and run one of the following commands.

_published:_

```
npm install @omarss/saas-dataplane-sdk@0.0.2 --save
```

_unPublished (not recommended):_

```
npm install PATH_TO_GENERATED_PACKAGE --save
```

### Documentation for API Endpoints

All URIs are relative to *https://dev.example.saas.omarss.net*

Class | Method | HTTP request | Description
------------ | ------------- | ------------- | -------------
*MetaApi* | [**getHealthz**](docs/MetaApi.md#gethealthz) | **GET** /healthz | Liveness probe.
*TenantsApi* | [**createTenant**](docs/TenantsApi.md#createtenant) | **POST** /v1/tenants | Create a tenant. Auto-creates a default Organization.
*TenantsApi* | [**deleteTenant**](docs/TenantsApi.md#deletetenant) | **DELETE** /v1/tenants/{tenant_id} | Soft-delete a tenant. Retention applies before physical purge.
*TenantsApi* | [**getTenant**](docs/TenantsApi.md#gettenant) | **GET** /v1/tenants/{tenant_id} | Fetch a tenant by id.
*TenantsApi* | [**listTenants**](docs/TenantsApi.md#listtenants) | **GET** /v1/tenants | List tenants visible to the caller\&#39;s Deployment.
*TenantsApi* | [**updateTenant**](docs/TenantsApi.md#updatetenant) | **PATCH** /v1/tenants/{tenant_id} | Update a tenant. Idempotent. ETag concurrency control required.


### Documentation For Models

 - [CreateTenantRequest](docs/CreateTenantRequest.md)
 - [FieldError](docs/FieldError.md)
 - [Health](docs/Health.md)
 - [Pagination](docs/Pagination.md)
 - [Problem](docs/Problem.md)
 - [Tenant](docs/Tenant.md)
 - [TenantListResponse](docs/TenantListResponse.md)
 - [TenantResponse](docs/TenantResponse.md)
 - [UpdateTenantRequest](docs/UpdateTenantRequest.md)


<a id="documentation-for-authorization"></a>
## Documentation For Authorization


Authentication schemes defined for the API:
<a id="bearerAuth"></a>
### bearerAuth

- **Type**: Bearer authentication (JWT)

<a id="apiKeyAuth"></a>
### apiKeyAuth

- **Type**: Bearer authentication (API key)

