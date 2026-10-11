from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Размерность колонки finding_embeddings.embedding (миграция 0017, под bge-m3)
EMBED_DIM = 1024


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

    # MCP-сервер для агентов (отдельный процесс: python -m app.mcp_server)
    mcp_host: str = "127.0.0.1"
    mcp_port: int = 8002

    # Redis / ARQ
    redis_url: str = "redis://localhost:6379/0"

    # Хранилище загруженных SARIF: local (папка на диске) или s3 (MinIO/S3, настройки ниже)
    storage_backend: str = "local"
    storage_path: str = "./data/sarif"

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

    # Встроенный ИИ: OpenAI-совместимый /v1/chat/completions. Пустой адрес — выключен.
    ai_base_url: str = ""
    ai_api_key: str = ""
    ai_model: str = ""
    ai_timeout: float = 60
    # сколько новых находок одного импорта разбирать автоматически; 0 — автозапуск выключен
    ai_auto_limit: int = 50

    # Эмбеддинги: OpenAI-совместимый /v1/embeddings. Пустая модель — векторы выключены.
    ai_embed_model: str = ""
    ai_embed_base_url: str = ""  # пусто — берётся ai_base_url
    ai_embed_dim: int = EMBED_DIM  # другая размерность — только с новой миграцией колонки

    @property
    def ai_enabled(self) -> bool:
        return bool(self.ai_base_url.strip())

    @property
    def embed_base_url(self) -> str:
        return (self.ai_embed_base_url or self.ai_base_url).strip()

    @property
    def embeddings_enabled(self) -> bool:
        return bool(self.ai_embed_model.strip() and self.embed_base_url)

    @model_validator(mode="after")
    def _embed_dim_matches_column(self) -> "Settings":
        # иначе вставка вектора падала бы ошибкой БД уже в воркере и в разборе ИИ
        if self.ai_embed_dim != EMBED_DIM:
            raise ValueError(
                f"SV_AI_EMBED_DIM={self.ai_embed_dim}: колонка векторов — {EMBED_DIM}, "
                "другая размерность требует миграции"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
