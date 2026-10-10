import ipaddress
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="IOP_", env_file=".env", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    database_url: SecretStr
    redis_url: SecretStr
    s3_endpoint: str
    s3_access_key: SecretStr
    s3_secret_key: SecretStr
    s3_bucket: str = "operations-private"
    cors_origins: list[str] = Field(default_factory=list)
    scanner_host: str | None = None
    scanner_port: int = Field(default=3310, ge=1, le=65535)
    otlp_endpoint: str | None = None
    oidc_issuer: str | None = None
    oidc_jwks_url: str | None = None
    oidc_audience: str | None = None
    oidc_profile: Literal["rfc9068", "keycloak"] = "rfc9068"
    api_rate_limit: int = Field(default=600, ge=1, le=100000)
    oidc_max_token_lifetime: int = Field(default=3600, ge=30, le=3600)
    email_profiles_directory: str | None = None
    webhook_private_egress_cidrs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_trust(self) -> Settings:
        configured = [self.oidc_issuer, self.oidc_jwks_url, self.oidc_audience]
        if any(configured) and not all(configured):
            raise ValueError("OIDC issuer, JWKS URL and audience must be configured together")
        if self.environment == "production":
            for endpoint in (self.oidc_issuer, self.oidc_jwks_url):
                if endpoint and urlparse(endpoint).scheme != "https":
                    raise ValueError("Production OIDC trust endpoints require HTTPS")
        try:
            networks = [
                ipaddress.ip_network(value, strict=False)
                for value in self.webhook_private_egress_cidrs
            ]
        except ValueError:
            raise ValueError("Webhook egress entries must be valid CIDRs") from None
        if any(
            not network.is_private
            or network.is_loopback
            or network.is_link_local
            or network.is_multicast
            or network.is_reserved
            for network in networks
        ):
            raise ValueError("Webhook egress CIDRs must name private deployment networks")
        return self
