from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """运行配置，容器内由 docker-compose 的 env_file 注入；本地直接运行时回退读取 .env。"""

    database_url: str = "postgresql+psycopg2://prereview:prereview@localhost:5434/prereview"
    redis_url: str = "redis://localhost:6380/0"

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-pro"

    ark_api_key: str = ""
    ark_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    ark_image_model: str = "doubao-seedream-4-0-250828"
    ark_chat_model: str = "doubao-seed-1-8-251228"

    upload_dir: str = "./uploads"
    sample_dir: str = "./sample_data"

    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "zhibiaoyun"
    minio_secure: bool = False

    cors_origins: str = "http://localhost:3000"

    secret_key: str = "dev-secret-change-me"
    access_token_expire_minutes: int = 60 * 24 * 7

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
