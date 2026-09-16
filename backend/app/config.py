from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # An absolute path, not ".env": that string is resolved against the
    # process's current working directory, which differs by launcher — the
    # documented dev workflow runs from backend/ (cwd = backend/, ".env"
    # resolves correctly), but IIS's httpPlatformHandler sets cwd to the
    # folder containing web.config (the site root, one level up). Under
    # that launcher ".env" silently resolved to nothing, every setting
    # with no default failed required-field validation, and the app never
    # started — anchoring to this file's own location makes it work
    # identically under either launcher.
    model_config = SettingsConfigDict(env_file=Path(__file__).resolve().parent.parent / ".env", env_file_encoding="utf-8")

    db_host: str = "127.0.0.1"
    db_port: int = 3306
    db_name: str = "aslg_legal"
    db_user: str
    db_password: str

    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 720

    # Read by backend/seed.py only (both the standalone `python seed.py` CLI
    # and the Factory Reset endpoint). Deliberately optional with no default
    # value here — seed.py itself refuses to create a user it needs a
    # password for when the corresponding variable is unset, rather than
    # falling back to any hardcoded value. See seed.py's own docstring for
    # why: this file previously shipped a hardcoded default that ended up
    # being the real, never-rotated production Admin password.
    seed_admin_password: str | None = Field(default=None, alias="ASLG_SEED_ADMIN_PASSWORD")
    seed_staff_password: str | None = Field(default=None, alias="ASLG_SEED_STAFF_PASSWORD")

    # Read by routers/internal.py's POST /api/internal/run-escalations only —
    # a shared secret the Windows Scheduled Task (description.md's
    # replacement for the "no scheduler in this app" gap) sends as a header,
    # since that endpoint has no logged-in user to authenticate as. NOT a
    # JWT and NOT a user password. Optional with no default, like the seed
    # passwords above: unset means the endpoint refuses every call rather
    # than falling back to any hardcoded value.
    internal_task_token: str | None = Field(default=None, alias="ASLG_INTERNAL_TASK_TOKEN")

    upload_dir: str = "./uploads"
    max_upload_mb: int = 25

    shared_assets_dir: str = r"C:\inetpub\sites\_shared"
    frontend_dir: str = "../"

    # Comma-separated list; the frontend is always served same-origin in
    # every real deployment, so the default covers only that production
    # host plus local dev — see the CORSMiddleware setup in main.py.
    cors_allowed_origins: str = "http://app.alsaiflegalgroup.com,https://app.alsaiflegalgroup.com,http://127.0.0.1:8000,http://localhost:8000"

    @property
    def allowed_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]

    @property
    def database_url(self) -> str:
        return (
            f"mysql+pymysql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}?charset=utf8mb4"
        )

    @property
    def upload_path(self) -> Path:
        # .resolve() is load-bearing, not cosmetic: every Document.storage_path
        # is saved as str(this_path / ...) at upload time and later re-opened
        # with a plain Path(storage_path).exists() check (documents.py). If
        # upload_dir is ever a relative value (the local-dev default,
        # "./uploads"), an unresolved Path here bakes a cwd-relative string
        # into the database — which only keeps resolving correctly if every
        # future process reads it from the exact same working directory it
        # was written from. That already broke in production once: rows
        # written while running from backend/ (dev/seed) came out relative,
        # then 404'd as "missing" when read back under IIS's httpPlatformHandler,
        # whose working directory is the site root, not backend/. Resolving
        # here means storage_path is always absolute going forward,
        # regardless of what's in .env or which launcher started the process.
        p = Path(self.upload_dir).resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p


settings = Settings()
