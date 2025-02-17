from pydantic_settings import BaseSettings
from functools import lru_cache
import os
from pathlib import Path
from typing import Optional
from loguru import logger
import sys


class Settings(BaseSettings):
    """Application settings"""
    # Environment Configuration
    ENV: str = os.getenv("APP_ENV", "development")  # 默认为开发环境

    # Gemini Configuration
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.0-flash"
    GEMINI_TEMPERATURE: float = 0.7
    GEMINI_MAX_TOKENS: int = 5000

    # Logging Configuration
    LOG_LEVEL: str = "DEBUG"

    # GitHub Configuration
    GITHUB_TOKEN: str = ""  # GitHub API token for checking updates
    GITHUB_OWNER: str = "DeJeune"
    GITHUB_REPO: str = "automation_financial_statements"

    # Base directory
    BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent

    # 应用数据目录 - 开发环境使用项目目录，生产环境使用系统目录
    APP_DATA_DIR: Path = (
        BASE_DIR if ENV == "development"
        else Path(os.getenv('LOCALAPPDATA', str(Path.home() / '.local' / 'share'))) / "Financial Automation"
    )
    APP_CONFIG_DIR: Path = APP_DATA_DIR / "config"
    APP_LOGS_DIR: Path = APP_DATA_DIR / "logs"
    APP_ASSETS_DIR: Path = APP_DATA_DIR / "assets"

    @classmethod
    def load_settings(cls) -> "Settings":
        """
        按优先级加载配置:
        1. 系统环境变量 (仅在生产环境)
        2. 用户数据目录下的配置文件
        3. 应用安装目录下的默认配置
        """
        # 获取环境
        env = os.getenv("APP_ENV", "development")

        # 获取基础目录
        if getattr(sys, 'frozen', False):
            # 打包后的应用
            app_dir = Path(sys.executable).parent
            if env == "production":
                app_data_dir = Path(os.getenv('LOCALAPPDATA')
                                    ) / "Financial Automation"
            else:
                app_data_dir = app_dir
            config_dir = app_data_dir / "config"
        else:
            # 开发环境
            app_dir = Path(__file__).parent.parent.parent
            app_data_dir = app_dir
            config_dir = app_data_dir / "config"

        # 确保必要的目录存在
        for directory in [app_data_dir, config_dir, app_data_dir / "logs", app_data_dir / "assets"]:
            directory.mkdir(parents=True, exist_ok=True)

        if env == "production":
            # 生产环境：加载环境变量
            logger.info("Loading production environment settings")
            settings = cls()
        else:
            # 开发环境：从配置文件加载
            # 可能的配置文件位置
            possible_env_files = [
                config_dir / '.env',  # 用户配置目录
                app_dir / '.env',     # 应用安装目录
                app_dir / 'config' / '.env',  # 应用配置目录
            ]

            # 查找第一个存在的配置文件
            env_file = next(
                (f for f in possible_env_files if f.exists()), None)

            if env_file:
                logger.info(
                    f"Loading development configuration from {env_file}")
                settings = cls(_env_file=env_file)
            else:
                logger.warning("No .env file found, using default settings")
                settings = cls()

        return settings

    class Config:
        env_file = ".env"
        env_file_encoding = 'utf-8'
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings"""
    return Settings.load_settings()
