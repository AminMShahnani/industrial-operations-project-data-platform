# ADR-0027: Mounted webhook secret resolver

Date: 2026-10-10  
Status: Accepted

## Context

ADR-0026 requires signing keys in an external tenant-scoped manager and leaves its
vendor to deployment. A worker needs a concrete deployment adapter so delivery can
be enabled without selecting a cloud provider or persisting credentials in Core.

## Decision

The worker supports a read-only mounted secret directory, populated by a deployment
secret manager or its CSI integration. Configure `IOP_WEBHOOK_SECRETS_DIRECTORY` to
an existing mount. Each file is named
`<organization-uuid>-<sha256(reference)>-v<version>.json` and contains exactly:

```json
{
  "organization_id": "<organization UUID>",
  "reference": "<exact opaque endpoint reference>",
  "version": 1,
  "key_base64": "<base64-encoded key of at least 32 bytes>"
}
```

The worker reads each version on demand, binds the contents to the requested tenant,
reference and key version, rejects symlink entries and non-regular/oversized/malformed
files, and emits only a generic unavailable error. The provider volume owns provisioning,
rotation, access policy, encryption and revocation. Key bytes stay in process memory
only for one signing attempt. No environment variable or database column contains
the key. When the directory is unset the worker remains fail-closed before claiming;
no attempt is consumed.

This is a deployment adapter contract, not a Core credential-management API. A
deployment may use any external secret manager that can maintain the documented
read-only file projection. Changing the file contract or adding a vendor SDK requires
a separate ADR.

## Consequences

Deployment must mount only the tenant/reference/version entries needed by the worker,
restrict the mount to the worker identity, and update the mount atomically during
rotation. Missing or mismatched keys fail closed with redacted errors. The application
cannot verify that a platform mount is encrypted or correctly permissioned; those are
deployment gates. Tests use temporary directories and never real key material.
