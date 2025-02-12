import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon
from pathlib import Path
from src.gui.main_window import MainWindow

def main():
    """Main application entry point"""
    app = QApplication(sys.argv)
    app_icon = str(Path(__file__).parent / "assets" / "app.ico")
    app.setWindowIcon(QIcon(app_icon))
    window = MainWindow()
    window.resize(800, 900)
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()