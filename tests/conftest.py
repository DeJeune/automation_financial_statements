"""Fixtures for the desktop application's processor tests."""

from datetime import date, datetime

import pytest

from src.config.shift_config import ShiftConfig


@pytest.fixture
def shift_config():
    return ShiftConfig(
        date(2026, 10, 16), datetime(2026, 10, 16, 8, 34, 40),
        datetime(2026, 10, 17, 8, 32, 40), 8.7,
    )
