"""
Centralized, fail-fast configuration for the FieldLine backend.

Phase 8b: replaces scattered os.environ.get(...) calls (each with its own
silent fallback) with one Settings object built ONCE, when this module is
first imported, that raises immediately if anything required is missing.
That turns a missing secret into a startup crash you see the moment you
run `uvicorn main:app`, instead of a confusing 500 error a technician
hits mid-shift.

Local development reads these from backend/.env (gitignored). In every
deployed environment, the exact same variable names are set directly in
that platform's own environment/secret store (Render calls this an
"Environment Group") -- never from a committed .env file.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # No default on any of these -- a missing value must crash startup,
    # not surface as a confusing error on the first request.
    database_url: str
    fieldline_jwt_secret: str
    moss_project_id: str
    moss_project_key: str

    # Phase 10: browser origins allowed to call this API, comma-separated.
    # The default is local development only; set CORS_ALLOWED_ORIGINS in
    # Render to include the deployed Vercel dashboard URL.
    cors_allowed_origins: str = "http://localhost:3000"


settings = Settings()