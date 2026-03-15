import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon, QFont
from pathlib import Path
from src.gui.main_window import MainWindow
from src.utils.updater import AppUpdater
from src.gui.components.update_dialog import UpdateDialog
from loguru import logger
import platform

def main():
    """Main application entry point"""
    app = QApplication(sys.argv) 
    app_icon = str(Path(__file__).parent / "assets" / "app.ico")
    app.setWindowIcon(QIcon(app_icon))
    
    # 设置全局字体
    if platform.system().lower() == 'windows':
        font = QFont("Microsoft YaHei", 10)
        font.setWeight(QFont.Weight.Medium)
    else:
        font = QFont('PingFang SC', 10)
        font.setWeight(QFont.Weight.Medium)
    
    app.setFont(font)
    
    window = MainWindow()
    window.resize(800, 800)
    window.show()

    # Auto-update check
    updater = AppUpdater()

    def _on_update_available(version: str, download_url: str, release_notes: str):
        dialog = UpdateDialog(updater, version, download_url, release_notes, parent=window)
        dialog.exec()

    updater.update_available.connect(_on_update_available)
    updater.check_error.connect(lambda msg: logger.debug(f"Update check failed: {msg}"))
    updater.check_for_updates()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()