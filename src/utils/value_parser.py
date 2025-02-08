from typing import Union, Optional
import re
from .logger import logger


def parse_numeric_value(
    value: Union[float, str],
    unit: Optional[str] = None,
    default_value: float = 0.0,
) -> float:
    """
    Parse a numeric value that could be either a float or a string with units.
    Handles cases where the value might come from ML model recognition in different formats.

    Args:
        value: The value to parse, either as float or string
        unit: Optional unit to strip from string (e.g., "元", "升")
        default_value: Value to return if parsing fails

    Returns:
        Parsed float value

    Examples:
        >>> parse_numeric_value(123.45)
        123.45
        >>> parse_numeric_value("123.45元", unit="元")
        123.45
        >>> parse_numeric_value("订单金额:456.78元", unit="元")  # Complex string
        456.78
        >>> parse_numeric_value("25,378.75")  # Number with commas
        25378.75
    """
    try:
        # If value is already a float, return it directly
        if isinstance(value, (int, float)):
            return float(value)

        # If value is string, clean and parse it
        if isinstance(value, str):
            # Remove all spaces and common currency symbols
            cleaned_value = value.strip()

            if unit:
                # Try to find number near the unit first
                # Split the string into segments that end with the unit
                segments = cleaned_value.split(unit)
                if len(segments) > 1:  # If unit is found in string
                    # Don't process the last segment after split
                    for i in range(len(segments)-1):
                        # Look for numbers in the current segment and at the start of next segment
                        current_segment = segments[i]
                        next_segment = segments[i+1]

                        # Try to find number at the end of current segment
                        numbers = re.findall(
                            r'[-+]?[\d,]*\.?\d+', current_segment)
                        if numbers:
                            # Take the last number before unit and remove commas
                            return float(numbers[-1].replace(",", ""))

                        # If no number in current segment, check start of next segment
                        numbers = re.findall(
                            r'[-+]?[\d,]*\.?\d+', next_segment)
                        if numbers:
                            # Take the first number after unit and remove commas
                            return float(numbers[0].replace(",", ""))

            # Remove spaces and currency symbols for general number search
            cleaned_value = cleaned_value.replace(
                " ", "").replace("¥", "").replace("$", "")

            # If no unit provided or unit not found, try to extract any number
            number_match = re.search(r'[-+]?[\d,]*\.?\d+', cleaned_value)
            if number_match:
                return float(number_match.group().replace(",", ""))

        # If parsing fails, log warning and return default
        logger.warning(
            f"Failed to parse numeric value: {value}, using default: {default_value}")
        return default_value

    except Exception as e:
        logger.error(f"Error parsing numeric value '{value}': {str(e)}")
        return default_value
