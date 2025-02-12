import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon, QFont
from pathlib import Path
from src.gui.main_window import MainWindow
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
    sys.exit(app.exec())

if __name__ == "__main__":
    main()