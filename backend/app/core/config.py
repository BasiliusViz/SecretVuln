from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="SV_", extra="ignore")

    app_name: str = "SecretVuln"
    debug: bool = False

    # Database
    database_url: str = "postgresql+asyncpg://secretvuln:secretvuln@localhost:5432/secretvuln"
    # Sync URL is derived for Alembic / Casbin adapter
    @property
    def database_url_sync(self) -> str:
        return self.database_url.replace("+asyncpg", "+psycopg")

    # Redis / ARQ
    redis_url: str = "redis://localhost:6379/0"

    # S3 / MinIO
    s3_endpoint_url: str = "http://localhost:9002"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "sarif-imports"

    # Auth
    # ВАЖНО: в проде задать свой (>=32 байт) через SV_JWT_SECRET
    jwt_secret: str = "dev-only-secret-change-me-in-production-0123456789"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 8

    # LDAP — дефолты под dev-контейнер lldap (docker-compose, профиль ldap)
    ldap_enabled: bool = True
    ldap_server: str = "ldap://localhost:3890"
    ldap_bind_dn: str = "uid=admin,ou=people,dc=secretvuln,dc=local"
    ldap_bind_password: str = "adminpassword"
    ldap_user_search_base: str = "ou=people,dc=secretvuln,dc=local"
    ldap_user_filter: str = "(mail={email})"
    ldap_group_search_base: str = "ou=groups,dc=secretvuln,dc=local"


@lru_cache
def get_settings() -> Settings:
    return Settings()
