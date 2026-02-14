from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://user:pass@localhost:5432/quantom"
    rabbitmq_url: str = "amqp://user:pass@localhost:5672/"
    tasks_exchange: str = "tasks.exchange"
    tasks_queue: str = "tasks.queue"
    tasks_routing_key: str = "tasks.queued"
    outbox_listen_channel: str = "outbox_new"
    outbox_batch_size: int = 100
    outbox_poll_interval_sec: int = 10
    outbox_max_attempts: int = 20

    model_config = {"env_prefix": ""}


settings = Settings()
