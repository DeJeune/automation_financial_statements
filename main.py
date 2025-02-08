import sys
from PySide6.QtWidgets import QApplication
from src.gui.main_window import MainWindow

def main():
    """Main application entry point"""
    app = QApplication(sys.argv)
    window = MainWindow()
    window.resize(800, 900)
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()