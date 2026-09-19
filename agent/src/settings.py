"""
Centralized, fail-fast configuration for the FieldLine agent process.

Phase 8b: moss_project_id, moss_project_key, and fieldline_jwt_secret have
no default -- a missing value crashes the moment agent.py imports this
module, not partway through a technician's first tool call.
fieldline_backend_url keeps a default: pointing at a local backend in dev
is a genuinely reasonable default, not an accidental one.

fieldline_jwt_secret MUST be byte-for-byte identical to the same variable
in backend/.env -- it's what lets agent/src/role_cache.py verify a
call-role token the backend minted, using nothing but local cryptography.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env.local", extra="ignore")

    moss_project_id: str
    moss_project_key: str
    fieldline_jwt_secret: str
    fieldline_backend_url: str = "http://localhost:8000"


settings = Settings()