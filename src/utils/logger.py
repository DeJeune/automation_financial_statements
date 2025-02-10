import sys
import os
from loguru import logger
from pathlib import Path
from src.config.settings import get_settings

settings = get_settings()


def get_log_path():
    """Get the appropriate log file path for both development and packaged environments"""
    if getattr(sys, 'frozen', False):
        # If the application is running in a bundle
        base_path = Path(sys._MEIPASS) if hasattr(
            sys, '_MEIPASS') else Path(sys.executable).parent
    else:
        # If running in development environment
        base_path = Path(__file__).parent.parent.parent

    # Create logs directory if it doesn't exist
    log_dir = base_path / 'logs'
    log_dir.mkdir(exist_ok=True)
    return str(log_dir / 'app.log')


def setup_logger():
    """Configure logging settings"""
    # Remove default handler
    logger.remove()

    try:
        # Add console handler
        logger.add(
            sys.stdout,
            format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
            level=settings.LOG_LEVEL,
            colorize=True
        )

        # Add file handler with proper error handling
        log_file = get_log_path()
        logger.add(
            log_file,
            rotation="500 MB",
            retention="10 days",
            format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
            level=settings.LOG_LEVEL,
            catch=True  # Catch exceptions that occur during logging
        )
    except Exception as e:
        # Fallback to console-only logging if file logging fails
        logger.warning(
            f"Failed to setup file logging: {str(e)}. Falling back to console logging only.")


# Initialize logger
setup_logger()
