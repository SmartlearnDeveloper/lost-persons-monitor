"""Utility helpers to read database configuration from env vars or config.json.

Having a single module allows every service (producer, dashboard, case_manager,
and scripts) to keep behavior aligned when migrating to Docker-based runtimes.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any, Dict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")


@lru_cache(maxsize=1)
def _load_file_config() -> Dict[str, Any]:
    if not os.path.exists(CONFIG_PATH):
        return {}

    with open(CONFIG_PATH, "r", encoding="utf-8") as config_file:
        return json.load(config_file)


def get_db_settings() -> Dict[str, Any]:
    """Return DB connection pieces honoring env overrides."""
    file_config = _load_file_config()
    return {
        "user": os.getenv("DB_USER", file_config.get("db_user", "user")),
        "password": os.getenv("DB_PASSWORD", file_config.get("db_password", "password")),
        "host": os.getenv("DB_HOST", file_config.get("db_host", "mysql")),
        "port": int(os.getenv("DB_PORT", file_config.get("db_port", 3306))),
        "name": os.getenv("DB_NAME", file_config.get("db_name", "lost_persons_db")),
        "root_password": os.getenv(
            "DB_ROOT_PASSWORD",
            os.getenv("MYSQL_ROOT_PASSWORD", file_config.get("db_root_password", "rootpassword")),
        ),
    }


def build_database_url(include_db: bool = True) -> str:
    """Compose a SQLAlchemy URL pointing at MySQL with mysqlconnector driver."""
    settings = get_db_settings()
    database = f"/{settings['name']}" if include_db else ""
    return (
        "mysql+mysqlconnector://"
        f"{settings['user']}:{settings['password']}@"
        f"{settings['host']}:{settings['port']}{database}"
    )


def build_root_admin_url() -> str:
    """Compose a SQLAlchemy URL using root credentials, no DB selected."""
    settings = get_db_settings()
    return (
        "mysql+mysqlconnector://"
        f"root:{settings['root_password']}@"
        f"{settings['host']}:{settings['port']}"
    )
