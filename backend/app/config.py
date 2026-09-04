"""Application configuration using pydantic-settings."""
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # App
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    DEBUG: bool = False

    # Database — set USE_SQLITE=true for lite mode (no PostgreSQL needed)
    # Default uses relative path for local dev; Docker overrides via env var
    USE_SQLITE: bool = True
    SQLITE_DB_PATH: str = "./dns_manager.db"
    POSTGRES_USER: str = "dns_admin"
    POSTGRES_PASSWORD: str = "ChangeMe123!"
    POSTGRES_DB: str = "dns_manager"
    POSTGRES_HOST: str = "postgres"
    POSTGRES_PORT: int = 5432

    @property
    def DATABASE_URL(self) -> str:
        if self.USE_SQLITE:
            import os
            db_path = os.environ.get("SQLITE_DB_PATH", self.SQLITE_DB_PATH)
            # Ensure parent directory exists
            db_dir = os.path.dirname(db_path)
            if db_dir:
                os.makedirs(db_dir, exist_ok=True)
            return f"sqlite+aiosqlite:///{db_path}"
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    # Redis
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = "ChangeMe123!"

    @property
    def REDIS_URL(self) -> str:
        return f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/0"

    # JWT
    JWT_SECRET: str = "change-this-to-a-random-secret-key"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 480

    # F5 Nodes
    F5_ACTIVE_HOST: str = "172.18.1.202"
    F5_SSH_PORT: int = 22
    F5_SSH_USER: str = "root"
    F5_SSH_PASSWORD: Optional[str] = None
    F5_SSH_KEY_PATH: str = "./ssh_keys/id_ed25519"
    F5_SSH_KEY_PASSPHRASE: Optional[str] = None

    # BIND paths on F5 (real filesystem; named chroot -t /var/named)
    F5_NAMED_CONF: str = "/var/named/config/named.conf"
    F5_ZONE_DIR: str = "/var/named/config/namedb"

    # Celery
    CELERY_BROKER_URL: Optional[str] = None

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
