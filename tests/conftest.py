import pytest
from fastapi.testclient import TestClient
from src.api.main import app

@pytest.fixture
def client():
    """Test client fixture"""
    return TestClient(app)

@pytest.fixture
def test_settings():
    """Test settings fixture"""
    from src.config.settings import Settings
    
    return Settings(
        API_V1_STR="/api/v1",
        PROJECT_NAME="Financial Statements Automation Test",
        LOG_LEVEL="DEBUG"
    ) 