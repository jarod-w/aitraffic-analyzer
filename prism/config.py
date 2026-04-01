from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PRISM_", env_file=".env", extra="ignore")

    # Server
    host: str = "0.0.0.0"
    port: int = 3000
    debug: bool = False

    # Database
    db_path: str = "/data/prism.db"
    db_url: str = ""  # If set, overrides db_path (use for PostgreSQL)

    # MITM Proxy
    mitm_host: str = "127.0.0.1"
    mitm_port: int = 8080

    # Storage
    data_dir: Path = Path("/data")
    certs_dir: Path = Path("/data/certs")
    scripts_dir: Path = Path("/scripts")
    uploads_dir: Path = Path("/data/uploads")

    # TLS
    ssl_keylog_file: str = ""  # SSLKEYLOGFILE path

    # Capture defaults
    default_capture_timeout: int = 120
    max_body_size: int = 10 * 1024 * 1024  # 10 MB
    max_pcap_size: int = 500 * 1024 * 1024  # 500 MB

    # Data retention
    data_retention_days: int = 30

    # Security
    redact_secrets: bool = True

    @property
    def effective_db_url(self) -> str:
        if self.db_url:
            return self.db_url
        return f"sqlite+aiosqlite:///{self.db_path}"

    def ensure_dirs(self):
        for d in (self.data_dir, self.certs_dir, self.scripts_dir, self.uploads_dir):
            d.mkdir(parents=True, exist_ok=True)


settings = Settings()
