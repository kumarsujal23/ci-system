"""
Central configuration. All tunables (timeouts, retry limits, lease durations)
live here so distributed-systems behavior is auditable in one place.
"""
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Core services
    database_url: str = "postgresql+psycopg2://ci:ci@postgres:5432/ci"
    redis_url: str = "redis://redis:6379/0"

    # Scheduling / leases
    job_lease_seconds: int = 60          # how long a worker holds a job before it's considered lost
    worker_heartbeat_seconds: int = 10   # expected heartbeat cadence
    worker_dead_after_seconds: int = 30  # no heartbeat for this long => worker considered dead
    reaper_interval_seconds: int = 5     # how often the scheduler sweeps for expired leases/dead workers

    # Retries (infrastructure failures only, never permanent build/test failures)
    max_job_attempts: int = 4
    retry_backoff_base_seconds: float = 2.0
    retry_backoff_max_seconds: float = 120.0

    # Docker execution
    docker_default_timeout_seconds: int = 900
    docker_default_memory: str = "512m"
    docker_default_cpus: float = 1.0
    docker_network_mode: str = "none"  # jobs get no network by default; opt-in per pipeline

    # AI Failure Analyzer
    ai_provider: str = "mock"          # "mock" | "anthropic" | "openai"
    ai_model: str = "claude-sonnet-4-6"
    ai_api_key: str = ""
    ai_timeout_seconds: int = 30
    ai_max_log_chars: int = 12000
    ai_max_source_files: int = 6
    ai_max_file_chars: int = 4000

    # Auth (kept intentionally simple for a portfolio project)
    webhook_secret: str = "change-me-webhook-secret"
    jwt_secret: str = "change-me-jwt-secret"

    # Websocket / pubsub
    log_channel_prefix: str = "ci:logs:"
    status_channel_prefix: str = "ci:status:"

    class Config:
        env_file = ".env"
        env_prefix = "CI_"


@lru_cache
def get_settings() -> Settings:
    return Settings()
