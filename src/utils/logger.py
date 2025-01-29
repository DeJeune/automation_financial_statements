import sys
from loguru import logger
from pathlib import Path
from src.config.settings import get_settings

settings = get_settings()

# Configure loguru logger
def setup_logger():
    """Configure logging settings"""
    # Remove default handler
    logger.remove()
    
    # Add console handler
    logger.add(
        sys.stdout,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
        level=settings.LOG_LEVEL,
        colorize=True
    )
    
    # Add file handler
    log_file = Path("logs/app.log")
    log_file.parent.mkdir(exist_ok=True)
    logger.add(
        str(log_file),
        rotation="500 MB",
        retention="10 days",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
        level=settings.LOG_LEVEL
    )

# Initialize logger
setup_logger() 