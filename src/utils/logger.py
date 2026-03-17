import sys
from loguru import logger
from src.config.settings import get_settings
from src.utils.app_paths import get_log_file_path

settings = get_settings()


def get_log_path():
    """Get the appropriate log file path for both development and packaged environments"""
    return str(get_log_file_path())


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
            retention="7 days",
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
