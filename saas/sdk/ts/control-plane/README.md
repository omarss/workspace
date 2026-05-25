## @omarss/saas-controlplane-sdk@0.1.0

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
npm install @omarss/saas-controlplane-sdk@0.1.0 --save
```

_unPublished (not recommended):_

```
npm install PATH_TO_GENERATED_PACKAGE --save
```

### Documentation for API Endpoints

All URIs are relative to *https://control.saas.omarss.net*

Class | Method | HTTP request | Description
------------ | ------------- | ------------- | -------------
*AuditApi* | [**listControlPlaneAuditEvents**](docs/AuditApi.md#listcontrolplaneauditevents) | **GET** /control/v1/audit-events | List control-plane operator audit events.
*AuditApi* | [**verifyDeploymentAuditIntegrity**](docs/AuditApi.md#verifydeploymentauditintegrity) | **GET** /control/v1/deployments/{deployment_id}/audit-integrity | Walk the audit chain and report the first mismatch (if any).
*DeploymentsApi* | [**createDeployment**](docs/DeploymentsApi.md#createdeployment) | **POST** /control/v1/deployments | Provision a new Deployment.
*DeploymentsApi* | [**deleteDeployment**](docs/DeploymentsApi.md#deletedeployment) | **DELETE** /control/v1/deployments/{deployment_id} | 
*DeploymentsApi* | [**freezeDeploymentKeys**](docs/DeploymentsApi.md#freezedeploymentkeys) | **POST** /control/v1/deployments/{deployment_id}/freeze-keys | 
*DeploymentsApi* | [**getDeployment**](docs/DeploymentsApi.md#getdeployment) | **GET** /control/v1/deployments/{deployment_id} | 
*DeploymentsApi* | [**getDeploymentHealth**](docs/DeploymentsApi.md#getdeploymenthealth) | **GET** /control/v1/deployments/{deployment_id}/health | 
*DeploymentsApi* | [**listDeploymentRevisions**](docs/DeploymentsApi.md#listdeploymentrevisions) | **GET** /control/v1/deployments/{deployment_id}/revisions | 
*DeploymentsApi* | [**listDeployments**](docs/DeploymentsApi.md#listdeployments) | **GET** /control/v1/deployments | List Deployments.
*DeploymentsApi* | [**purgeDeployment**](docs/DeploymentsApi.md#purgedeployment) | **POST** /control/v1/deployments/{deployment_id}/purge | 
*DeploymentsApi* | [**restartDeployment**](docs/DeploymentsApi.md#restartdeployment) | **POST** /control/v1/deployments/{deployment_id}/restart | 
*DeploymentsApi* | [**restoreDeployment**](docs/DeploymentsApi.md#restoredeployment) | **POST** /control/v1/deployments/{deployment_id}/restore | 
*DeploymentsApi* | [**rollbackDeployment**](docs/DeploymentsApi.md#rollbackdeployment) | **POST** /control/v1/deployments/{deployment_id}/rollback | 
*DeploymentsApi* | [**startImpersonationSession**](docs/DeploymentsApi.md#startimpersonationsession) | **POST** /control/v1/deployments/{deployment_id}/impersonation-sessions | 
*DeploymentsApi* | [**tailDeploymentLogs**](docs/DeploymentsApi.md#taildeploymentlogs) | **GET** /control/v1/deployments/{deployment_id}/logs | 
*DeploymentsApi* | [**updateDeployment**](docs/DeploymentsApi.md#updatedeployment) | **PATCH** /control/v1/deployments/{deployment_id} | 
*DeploymentsApi* | [**upgradeDeployment**](docs/DeploymentsApi.md#upgradedeployment) | **POST** /control/v1/deployments/{deployment_id}/upgrade | 
*DomainsApi* | [**attachDeploymentDomain**](docs/DomainsApi.md#attachdeploymentdomain) | **POST** /control/v1/deployments/{deployment_id}/domains | 
*DomainsApi* | [**detachDeploymentDomain**](docs/DomainsApi.md#detachdeploymentdomain) | **DELETE** /control/v1/deployments/{deployment_id}/domains/{domain_id} | 
*DomainsApi* | [**getDeploymentDomain**](docs/DomainsApi.md#getdeploymentdomain) | **GET** /control/v1/deployments/{deployment_id}/domains/{domain_id} | 
*DomainsApi* | [**listDeploymentDomains**](docs/DomainsApi.md#listdeploymentdomains) | **GET** /control/v1/deployments/{deployment_id}/domains | 
*DomainsApi* | [**verifyDeploymentDomain**](docs/DomainsApi.md#verifydeploymentdomain) | **POST** /control/v1/deployments/{deployment_id}/domains/{domain_id}/verify | 
*MetaApi* | [**getHealthz**](docs/MetaApi.md#gethealthz) | **GET** /healthz | Liveness probe.
*OperatorsApi* | [**listOperators**](docs/OperatorsApi.md#listoperators) | **GET** /control/v1/operators | List operators (Phase 13 extends with MFA status).


### Documentation For Models

 - [AttachDomainRequest](docs/AttachDomainRequest.md)
 - [AuditIntegrityResponse](docs/AuditIntegrityResponse.md)
 - [AuditIntegrityResponseData](docs/AuditIntegrityResponseData.md)
 - [ControlPlaneAuditEvent](docs/ControlPlaneAuditEvent.md)
 - [ControlPlaneAuditEventListResponse](docs/ControlPlaneAuditEventListResponse.md)
 - [CreateDeploymentRequest](docs/CreateDeploymentRequest.md)
 - [CreateDeploymentResponse](docs/CreateDeploymentResponse.md)
 - [CreateDeploymentResponseBootstrapApiKey](docs/CreateDeploymentResponseBootstrapApiKey.md)
 - [Deployment](docs/Deployment.md)
 - [DeploymentDomain](docs/DeploymentDomain.md)
 - [DeploymentDomainListResponse](docs/DeploymentDomainListResponse.md)
 - [DeploymentDomainResponse](docs/DeploymentDomainResponse.md)
 - [DeploymentDomainVerificationRecord](docs/DeploymentDomainVerificationRecord.md)
 - [DeploymentHealth](docs/DeploymentHealth.md)
 - [DeploymentHealthComponentsInner](docs/DeploymentHealthComponentsInner.md)
 - [DeploymentHealthResponse](docs/DeploymentHealthResponse.md)
 - [DeploymentListResponse](docs/DeploymentListResponse.md)
 - [DeploymentResponse](docs/DeploymentResponse.md)
 - [DeploymentRevision](docs/DeploymentRevision.md)
 - [DeploymentRevisionListResponse](docs/DeploymentRevisionListResponse.md)
 - [Health](docs/Health.md)
 - [Operator](docs/Operator.md)
 - [OperatorListResponse](docs/OperatorListResponse.md)
 - [Pagination](docs/Pagination.md)
 - [RestoreDeploymentRequest](docs/RestoreDeploymentRequest.md)
 - [StartImpersonationRequest](docs/StartImpersonationRequest.md)
 - [StartImpersonationResponse](docs/StartImpersonationResponse.md)
 - [UpdateDeploymentRequest](docs/UpdateDeploymentRequest.md)
 - [UpgradeDeploymentRequest](docs/UpgradeDeploymentRequest.md)


<a id="documentation-for-authorization"></a>
## Documentation For Authorization

Endpoints do not require authorization.

