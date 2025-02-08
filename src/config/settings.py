from pydantic_settings import BaseSettings
from functools import lru_cache
import os
from pathlib import Path
from typing import Optional
from loguru import logger
import sys


class Settings(BaseSettings):
    """Application settings"""
    # API Configuration
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "Financial Statements Automation"

    # Base directory
    BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent

    # Model Configuration
    MODEL_PATH: str = str(BASE_DIR / "models" / "configs")

    # Gemini Configuration
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.0-flash"
    GEMINI_TEMPERATURE: float = 0.7
    GEMINI_MAX_TOKENS: int = 5000

    # Logging Configuration
    LOG_LEVEL: str = "DEBUG"

    @classmethod
    def load_settings(cls) -> "Settings":
        """
        按优先级加载配置:
        1. 系统环境变量
        2. 用户目录下的 .env 文件 (适用于打包后)
        3. 应用目录下的默认 .env 文件
        """
        # 获取可执行文件所在目录
        if getattr(sys, 'frozen', False):
            # 如果是打包后的应用
            app_dir = Path(sys.executable).parent
        else:
            # 如果是开发环境
            app_dir = Path(__file__).parent.parent.parent

        # 可能的配置文件位置
        possible_env_files = [
            Path.cwd() / '.env',  # 当前工作目录
            app_dir / '.env',     # 应用安装目录
            app_dir / 'config' / '.env',  # 应用配置目录
        ]

        # 查找第一个存在的配置文件
        env_file = next((f for f in possible_env_files if f.exists()), None)

        if env_file:
            logger.info(f"Loading configuration from {env_file}")
            return cls(_env_file=env_file)
        else:
            logger.warning("No .env file found, using default settings")
            return cls()

    class Config:
        env_file = ".env"
        env_file_encoding = 'utf-8'
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings"""
    return Settings.load_settings()
