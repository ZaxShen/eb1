from pydantic import computed_field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Vercel AI Gateway — single key for all LLM providers (benchmark + pipeline)
    ai_gateway_api_key: str | None = None

    # ── PostgreSQL (pipeline writes + reads) ────────────────────────
    postgres_dsn: str = ""

    # ── MongoDB Output (legacy — being replaced by PostgreSQL) ────
    mongodb_output_uri: str = ""
    mongodb_output_db_name: str = "eb1"

    # ── Input (reads) ────────────────────────────────────────────────
    # PROD Analytics replica — read-only input for the pipeline.
    # Leave unset to read from the output DB.
    mongodb_prod_analytics_uri: str | None = None
    mongodb_prod_analytics_db_name: str | None = None

    # ── Resolved properties (consumed by db/client.py) ───────────────

    @computed_field
    @property
    def mongodb_uri(self) -> str:
        return self.mongodb_output_uri

    @computed_field
    @property
    def mongodb_db_name(self) -> str:
        return self.mongodb_output_db_name

    @computed_field
    @property
    def mongodb_input_uri(self) -> str | None:
        return self.mongodb_prod_analytics_uri

    @computed_field
    @property
    def mongodb_input_db_name(self) -> str | None:
        return self.mongodb_prod_analytics_db_name

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
