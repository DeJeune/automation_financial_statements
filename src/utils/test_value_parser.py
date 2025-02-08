import pytest
from .value_parser import parse_numeric_value


@pytest.mark.parametrize("test_input,unit,expected", [
    # Test basic numeric values
    (123.45, None, 123.45),
    (0, None, 0.0),
    (-123.45, None, -123.45),

    # Test string numbers without units
    ("123.45", None, 123.45),
    ("-123.45", None, -123.45),
    ("0", None, 0.0),

    # Test values with units (no space)
    ("123.45元", "元", 123.45),
    ("123元", "元", 123.0),
    ("45.67升", "升", 45.67),

    # Test values with units (with space)
    ("123.45 元", "元", 123.45),
    ("123 元", "元", 123.0),
    ("45.67 升", "升", 45.67),

    # Test values with currency symbols
    ("¥123.45", None, 123.45),
    ("$123.45", None, 123.45),
    ("¥123.45元", "元", 123.45),
    ("$123.45元", "元", 123.45),

    # Test values with multiple numbers (should take first valid number)
    ("订单金额123.45元找零6.55元", "元", 123.45),
    ("总计: 123.45元 (税费: 10.00元)", "元", 123.45),

    # Test edge cases
    ("", None, 0.0),  # Empty string should return default
    ("no numbers here", None, 0.0),  # No numbers should return default
    ("元123.45", "元", 123.45),  # Unit before number
])
def test_parse_numeric_value(test_input, unit, expected):
    """Test parse_numeric_value with various input formats."""
    result = parse_numeric_value(test_input, unit=unit)
    assert result == expected, f"Failed to parse '{test_input}' with unit '{unit}'"


def test_parse_numeric_value_with_custom_default():
    """Test parse_numeric_value with custom default value."""
    custom_default = -1.0
    result = parse_numeric_value("invalid input", default_value=custom_default)
    assert result == custom_default


def test_parse_numeric_value_error_cases():
    """Test parse_numeric_value error handling."""
    # Test with None input
    assert parse_numeric_value(None) == 0.0

    # Test with invalid types
    assert parse_numeric_value({}) == 0.0
    assert parse_numeric_value([]) == 0.0

    # Test with invalid string formats
    assert parse_numeric_value("abc") == 0.0
    assert parse_numeric_value("元") == 0.0


def test_parse_numeric_value_with_complex_strings():
    """Test parse_numeric_value with more complex string inputs."""
    test_cases = [
        ("订单编号:123 金额:456.78元", "元", 456.78),
        ("共计消费¥789.12 (含服务费)", None, 789.12),
        ("价格:123.45元\n数量:2", "元", 123.45),
        ("金额：¥123.45（已优惠：¥10）", None, 123.45),
        ("单价:123.45元/升", "元", 123.45),
        ("25,378.75", None, 25378.75),
        ("25,378.75元", "元", 25378.75),
        ("2,225,378.75元", "元", 2225378.75),
    ]

    for test_input, unit, expected in test_cases:
        result = parse_numeric_value(test_input, unit=unit)
        assert result == expected, f"Failed to parse complex string: '{test_input}'"
