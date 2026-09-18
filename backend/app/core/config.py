import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BACKEND_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(BACKEND_ROOT / ".env")


def _csv_env(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "SPDX LIMS API")
    app_env: str = os.getenv("APP_ENV", "dev")
    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://lims_user:lims_password@localhost:5432/lims_db",
    )
    jwt_secret_key: str = os.getenv("JWT_SECRET_KEY", "change-this-in-production")
    jwt_algorithm: str = os.getenv("JWT_ALGORITHM", "HS256")
    jwt_expire_minutes: int = int(os.getenv("JWT_EXPIRE_MINUTES", "480"))
    # Lowest order number this database may issue. The lab runs more than one
    # database - some orders are placed locally, some here - and an analyzer
    # result is matched to an order by its number, so two databases issuing the
    # same number would import one patient's run onto another patient's order.
    # Giving each its own range keeps them apart. 0 means "no floor".
    order_number_floor: int = int(os.getenv("ORDER_NUMBER_FLOOR", "0"))
    cors_origins: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "cors_origins",
            _csv_env("CORS_ORIGINS", "http://localhost:8001,http://127.0.0.1:8001"),
        )
        if self.app_env.lower() in {"prod", "production"} and self.jwt_secret_key == "change-this-in-production":
            raise RuntimeError("JWT_SECRET_KEY must be set to a strong value in production.")


settings = Settings()
