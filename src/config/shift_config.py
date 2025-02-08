from datetime import date, datetime
from dataclasses import dataclass


@dataclass
class ShiftConfig:
    """Configuration class for shift-related parameters"""
    date: date
    work_start_time: datetime
    shift_time: datetime
    gas_price: float

    def __post_init__(self):
        """Validate the configuration parameters"""
        if not isinstance(self.date, date):
            raise ValueError("date must be a date object")
        if not isinstance(self.work_start_time, datetime):
            raise ValueError("work_start_time must be a datetime object")
        if not isinstance(self.shift_time, datetime):
            raise ValueError("shift_time must be a datetime object")
        if not isinstance(self.gas_price, (int, float)):
            raise ValueError("gas_price must be a number")
        if self.gas_price <= 0:
            raise ValueError("gas_price must be positive")
