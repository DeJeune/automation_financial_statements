import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon, QFont
from pathlib import Path
from src.gui.main_window import MainWindow
import platform
from src.config.settings import get_settings


def main():
    """Main application entry point"""
    app = QApplication(sys.argv)

    # 获取配置
    settings = get_settings()

    # 根据环境加载图标
    if getattr(sys, 'frozen', False):
        # 生产环境 - 从 LOCALAPPDATA/assets 加载
        app_icon = str(settings.APP_ASSETS_DIR / "app.ico")
    else:
        # 开发环境 - 从项目目录加载
        app_icon = str(Path(__file__).parent / "assets" / "app.ico")

    # 设置应用图标
    if Path(app_icon).exists():
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
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
