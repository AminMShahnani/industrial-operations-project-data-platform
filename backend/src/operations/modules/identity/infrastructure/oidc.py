from typing import Protocol

import jwt
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from operations.contracts import ServiceError
from operations.modules.identity.application.contracts import Principal
from operations.platform.config import Settings


class Claims(BaseModel):
    model_config = ConfigDict(strict=True)
    sub: str = Field(min_length=1, max_length=255)
    iss: str = Field(min_length=1, max_length=500)
    email: str | None = None
    email_verified: bool = False
    exp: int
    iat: int


class KeyResolver(Protocol):
    def key(self, token: str) -> RSAPublicKey: ...


class JwksResolver:
    def __init__(self, url: str) -> None:
        self.client = jwt.PyJWKClient(url, timeout=3, lifespan=300)

    def key(self, token: str) -> RSAPublicKey:
        key = self.client.get_signing_key_from_jwt(token).key
        if not isinstance(key, RSAPublicKey):
            raise ServiceError(401, "invalid_token")
        return key


class OidcVerifier:
    def __init__(self, settings: Settings, resolver: KeyResolver | None = None) -> None:
        self.settings = settings
        self.resolver = resolver or (
            JwksResolver(settings.oidc_jwks_url) if settings.oidc_jwks_url else None
        )

    def verify(self, token: str) -> Principal:
        if not self.resolver or not self.settings.oidc_issuer or not self.settings.oidc_audience:
            raise ServiceError(503, "authentication_not_configured")
        if len(token) > 16384:
            raise ServiceError(401, "invalid_token")
        try:
            header = jwt.get_unverified_header(token)
            expected_type = "at+jwt" if self.settings.oidc_profile == "rfc9068" else "JWT"
            if header.get("alg") != "RS256" or header.get("typ") != expected_type:
                raise ServiceError(401, "invalid_token")
            payload = jwt.decode(
                token,
                self.resolver.key(token),
                algorithms=["RS256"],
                issuer=self.settings.oidc_issuer,
                audience=self.settings.oidc_audience,
                options={"require": ["exp", "iat", "iss", "sub", "aud"]},
            )
            if self.settings.oidc_profile == "keycloak" and payload.get("typ") != "Bearer":
                raise ServiceError(401, "invalid_token")
            claims = Claims.model_validate(payload)
            if (
                claims.exp <= claims.iat
                or claims.exp - claims.iat > self.settings.oidc_max_token_lifetime
            ):
                raise ServiceError(401, "invalid_token")
            return Principal(claims.iss, claims.sub, claims.email, claims.email_verified)
        except (jwt.PyJWTError, ValidationError, ValueError) as error:
            raise ServiceError(401, "invalid_token") from error
