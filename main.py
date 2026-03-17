import sys
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtGui import QIcon, QFont
from src.gui.main_window import MainWindow
from src.utils.updater import AppUpdater
from src.gui.components.update_dialog import UpdateDialog
from loguru import logger
import platform
from src.utils.app_paths import get_asset_path, get_log_file_path

def main():
    """Main application entry point"""
    app = QApplication(sys.argv) 
    app_icon = get_asset_path("app.ico")
    if app_icon.exists():
        app.setWindowIcon(QIcon(str(app_icon)))
    
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


def _show_startup_error(exc: Exception) -> None:
    log_file = get_log_file_path()
    app = QApplication.instance() or QApplication(sys.argv)
    QMessageBox.critical(
        None,
        "启动失败",
        f"应用启动失败：{exc}\n\n详细日志：{log_file}",
    )

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        logger.exception("Application startup failed")
        try:
            _show_startup_error(exc)
        except Exception:
            pass
        raise
