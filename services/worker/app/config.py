from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://user:pass@localhost:5432/quantom"
    rabbitmq_url: str = "amqp://user:pass@localhost:5672/"
    tasks_exchange: str = "tasks.exchange"
    tasks_queue: str = "tasks.queue"
    tasks_routing_key: str = "tasks.queued"
    shots: int = 1024

    model_config = {"env_prefix": ""}


settings = Settings()

if settings.shots <= 0:
    raise ValueError(f"SHOTS must be a positive integer, got {settings.shots}")
