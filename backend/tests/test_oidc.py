from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from operations.contracts import ServiceError
from operations.modules.identity.infrastructure.oidc import OidcVerifier
from operations.platform.config import Settings


class Resolver:
    def __init__(self, key: rsa.RSAPublicKey) -> None:
        self.public_key = key

    def key(self, token: str) -> rsa.RSAPublicKey:
        return self.public_key


@pytest.fixture
def signing_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def access_token(
    key: rsa.RSAPrivateKey,
    subject: str = "admin",
    email: str = "admin@example.com",
    /,
    **changes: object,
) -> str:
    now = datetime.now(UTC)
    payload: dict[str, object] = {
        "iss": "https://identity.example.test",
        "aud": "operations-api",
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(minutes=5),
        "email": email,
        "email_verified": True,
    }
    payload.update(changes)
    return jwt.encode(payload, key, algorithm="RS256", headers={"typ": "at+jwt", "kid": "test-key"})


def configured(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            "oidc_issuer": "https://identity.example.test",
            "oidc_audience": "operations-api",
            "oidc_jwks_url": "https://identity.example.test/jwks",
        }
    )


def test_valid_access_token(settings: Settings, signing_key: rsa.RSAPrivateKey) -> None:
    verifier = OidcVerifier(configured(settings), Resolver(signing_key.public_key()))
    principal = verifier.verify(access_token(signing_key))
    assert principal.subject == "admin"
    assert principal.email_verified


@pytest.mark.parametrize(
    "changes",
    [
        {"iss": "https://attacker.test"},
        {"aud": "browser-id-token"},
        {"exp": 1},
        {"iat": 9999999999},
        {"sub": ""},
        {"email_verified": "true"},
        {"exp": datetime.now(UTC) + timedelta(hours=2)},
        {"sub": "a" * 256},
    ],
)
def test_invalid_claims(
    settings: Settings,
    signing_key: rsa.RSAPrivateKey,
    changes: dict[str, object],
) -> None:
    verifier = OidcVerifier(configured(settings), Resolver(signing_key.public_key()))
    with pytest.raises(ServiceError) as denied:
        verifier.verify(access_token(signing_key, **changes))
    assert denied.value.status == 401


def test_id_tokens_unsigned_and_forged_tokens_deny(
    settings: Settings,
    signing_key: rsa.RSAPrivateKey,
) -> None:
    verifier = OidcVerifier(configured(settings), Resolver(signing_key.public_key()))
    attacker = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    forged = access_token(attacker)
    payload = jwt.decode(access_token(signing_key), options={"verify_signature": False})
    id_token = jwt.encode(payload, signing_key, algorithm="RS256", headers={"typ": "JWT"})
    unsigned = jwt.encode(payload, key="", algorithm="none", headers={"typ": "at+jwt"})
    missing_exp = dict(payload)
    missing_exp.pop("exp")
    missing = jwt.encode(missing_exp, signing_key, algorithm="RS256", headers={"typ": "at+jwt"})
    for token in (forged, id_token, unsigned, missing, "malformed", "a" * 16385):
        with pytest.raises(ServiceError):
            verifier.verify(token)


def test_missing_trust_fails_closed(settings: Settings) -> None:
    with pytest.raises(ServiceError) as denied:
        OidcVerifier(settings).verify("anything")
    assert denied.value.status == 503


def test_keycloak_profile_does_not_accept_id_tokens(
    settings: Settings,
    signing_key: rsa.RSAPrivateKey,
) -> None:
    config = configured(settings).model_copy(update={"oidc_profile": "keycloak"})
    verifier = OidcVerifier(config, Resolver(signing_key.public_key()))
    payload = jwt.decode(access_token(signing_key), options={"verify_signature": False})
    payload["typ"] = "Bearer"
    valid = jwt.encode(payload, signing_key, algorithm="RS256", headers={"typ": "JWT"})
    assert verifier.verify(valid).subject == "admin"
    payload["typ"] = "ID"
    with pytest.raises(ServiceError):
        verifier.verify(jwt.encode(payload, signing_key, algorithm="RS256", headers={"typ": "JWT"}))
