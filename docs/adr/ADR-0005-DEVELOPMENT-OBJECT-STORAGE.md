# ADR-0005: Registry-verified development infrastructure

Status: Accepted
Date: 2026-10-05

## Context
The first hosted CI run failed at Compose startup. Local cached PostgreSQL and
MinIO RepoDigests were not usable remote references: PostgreSQL manifest
verification failed, Docker Hub denied MinIO access, and Quay returned 401.
Local cache availability therefore did not establish reproducibility.

## Decision
Pin PostgreSQL 16 and Redis 7 using registry-verified OCI index digests. Use the
official RustFS image, also pinned by registry digest, for development and CI
S3 compatibility. Core retains its boto3 S3 adapter and private-bucket contract;
no industry semantics or production storage provider choice changes.
Validate actual bucket creation, policy behavior, API readiness and denied
anonymous access with the replacement before accepting Phase 0.

## Data and rollback
Use a separate `rustfs_data` volume. Retain the existing `storage_data` volume;
do not mount MinIO data into another implementation or delete it. No operational
uploads or data conversion have been requested or performed. Existing external
production S3 endpoints are unaffected. Any future storage-data migration needs
its own inventory, checksums, parallel validation and rollback plan.

To roll back development infrastructure, stop this project's services without
deleting volumes and restore the prior Compose configuration using its cached
images. The previous MinIO volume remains intact. This fallback is local only;
unavailable upstream images are not an acceptable fresh-install dependency.

## Sources
- https://github.com/minio/minio
- https://github.com/rustfs/rustfs
- https://docs.rustfs.com/en/installation/container

Registry digests are resolved using `docker buildx imagetools inspect`, rather
than inferred from local image IDs. Production storage selection and hardening
remain separate release work.
