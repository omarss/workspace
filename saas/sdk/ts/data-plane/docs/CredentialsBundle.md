# CredentialsBundle

Per-provider credential bundle. Exactly one of smtp / sendgrid / ses is populated based on the channel provider; the in_app provider rejects any credential payload. 

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**smtp** | [**SMTPCredentials**](SMTPCredentials.md) |  | [optional] [default to undefined]
**sendgrid** | [**SendGridCredentials**](SendGridCredentials.md) |  | [optional] [default to undefined]
**ses** | [**SESCredentials**](SESCredentials.md) |  | [optional] [default to undefined]

## Example

```typescript
import { CredentialsBundle } from '@omarss/saas-dataplane-sdk';

const instance: CredentialsBundle = {
    smtp,
    sendgrid,
    ses,
};
```

[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
