from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://user:pass@localhost:5432/quantom"
    max_qc_size_bytes: int = 1_048_576  # 1MB

    model_config = {"env_prefix": ""}


settings = Settings()
