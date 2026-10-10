import base64
import json
from pathlib import Path
from uuid import uuid7

import pytest
from operations.contracts import ServiceError
from operations.modules.integrations.application.webhooks import MountedTenantSecretResolver


def test_mounted_secret_resolution_is_tenant_reference_and_version_bound(tmp_path: Path) -> None:
    organization = uuid7()
    reference = "tenant/webhooks/key-current"
    secret = bytes(range(32))
    resolver = MountedTenantSecretResolver(tmp_path)
    path = resolver._path(organization, reference, 4)
    path.write_text(
        json.dumps(
            {
                "organization_id": str(organization),
                "reference": reference,
                "version": 4,
                "key_base64": base64.b64encode(secret).decode("ascii"),
            }
        ),
        encoding="utf-8",
    )

    assert resolver.resolve(organization, reference, 4) == secret
    for org, ref, version in (
        (uuid7(), reference, 4),
        (organization, "tenant/webhooks/other", 4),
        (organization, reference, 5),
    ):
        with pytest.raises(ServiceError) as error:
            resolver.resolve(org, ref, version)
        assert error.value.code == "webhook_signing_secret_unavailable"


def test_mounted_secret_rejects_identity_mismatch_and_short_key(tmp_path: Path) -> None:
    organization = uuid7()
    reference = "tenant/webhooks/key-current"
    resolver = MountedTenantSecretResolver(tmp_path)
    path = resolver._path(organization, reference, 1)
    path.write_text(
        json.dumps(
            {
                "organization_id": str(uuid7()),
                "reference": reference,
                "version": 1,
                "key_base64": base64.b64encode(bytes(range(32))).decode("ascii"),
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ServiceError) as error:
        resolver.resolve(organization, reference, 1)
    assert error.value.code == "webhook_signing_secret_unavailable"

    path.write_text(
        json.dumps(
            {
                "organization_id": str(organization),
                "reference": reference,
                "version": 1,
                "key_base64": base64.b64encode(b"short").decode("ascii"),
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ServiceError) as error:
        resolver.resolve(organization, reference, 1)
    assert error.value.code == "webhook_signing_secret_unavailable"
