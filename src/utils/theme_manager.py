"""Theme management utilities for the application."""

from PySide6.QtCore import QSettings
from src.gui.styles import LIGHT_THEME, DARK_THEME


class ThemeManager:
    """Manages application theme settings and provides theme-related utilities."""

    def __init__(self):
        """Initialize the theme manager with application settings."""
        self.settings = QSettings('YourCompany', 'InvoiceProcessor')

    def get_current_theme(self) -> str:
        """
        Get the current theme setting.

        Returns:
            str: The current theme ('light' or 'dark')
        """
        return self.settings.value('theme', 'light')

    def set_theme(self, theme: str) -> None:
        """
        Set the current theme.

        Args:
            theme (str): The theme to set ('light' or 'dark')
        """
        self.settings.setValue('theme', theme)

    def get_theme_style(self) -> str:
        """
        Get the stylesheet for the current theme.

        Returns:
            str: The stylesheet for the current theme
        """
        theme = self.get_current_theme()
        return DARK_THEME if theme == 'dark' else LIGHT_THEME
