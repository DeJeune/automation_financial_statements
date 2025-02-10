from PySide6.QtCore import QSettings

# Light Theme
LIGHT_THEME = """
/* Main Window and Basic Widgets */
QMainWindow, QWidget {
    background-color: #ffffff;
    color: #333333;
}

/* Tab Widget and Sidebar */
QTabWidget {
    background: #f5f5f5;
    border: none;
}

QTabWidget::pane {
    border: none;
    background: #f5f5f5;
}

QTabWidget::tab-bar {
    alignment: left;
    left: 0;
    top: 5px;
}

QTabBar::tab {
    padding: 8px 20px;
    color: #666666;
    background: #f5f5f5;
    border: none;
    font-size: 13px;
    font-weight: bold;
    width: 120px;
    margin: 1px 0;
    text-align: center;
}

QTabBar::tab:selected {
    color: #2196F3;
    background: #ffffff;
    border-left: 4px solid #2196F3;
}

QTabBar::tab:hover:!selected {
    color: #2196F3;
    background: #e0e0e0;
}

/* Group Boxes */
QGroupBox {
    background-color: #ffffff;
    border: 2px solid #e0e0e0;
    border-radius: 6px;
    margin-top: 1ex;
    font-weight: bold;
    color: #333333;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 5px;
    color: #2196F3;
}

/* Buttons */
QPushButton {
    background-color: #2196F3;
    color: white;
    border: none;
    padding: 8px 16px;
    border-radius: 4px;
    min-width: 80px;
}

QPushButton:hover {
    background-color: #1976D2;
}

QPushButton:pressed {
    background-color: #0D47A1;
}

QPushButton:disabled {
    background-color: #BDBDBD;
}

/* Table Widget */
QTableWidget {
    background-color: #ffffff;
    alternate-background-color: #f5f5f5;
    color: #333333;
    gridline-color: #e0e0e0;
    selection-background-color: #2196F3;
    selection-color: white;
    border: 1px solid #e0e0e0;
}

QHeaderView::section {
    background-color: #f5f5f5;
    color: #333333;
    padding: 5px;
    border: none;
    border-right: 1px solid #e0e0e0;
    border-bottom: 1px solid #e0e0e0;
}

/* Scroll Bars */
QScrollBar:vertical {
    background: #f5f5f5;
    width: 12px;
    margin: 0;
}

QScrollBar::handle:vertical {
    background: #bdbdbd;
    min-height: 30px;
    border-radius: 6px;
}

QScrollBar::handle:vertical:hover {
    background: #9e9e9e;
}

QScrollBar:horizontal {
    background: #f5f5f5;
    height: 12px;
    margin: 0;
}

QScrollBar::handle:horizontal {
    background: #bdbdbd;
    min-width: 30px;
    border-radius: 6px;
}

QScrollBar::handle:horizontal:hover {
    background: #9e9e9e;
}

/* Text Inputs */
QLineEdit, QSpinBox, QDoubleSpinBox {
    background-color: #ffffff;
    color: #333333;
    border: 1px solid #e0e0e0;
    border-radius: 4px;
    padding: 5px;
    min-height: 30px;
}

QDateTimeEdit {
    background-color: #ffffff;
    color: #333333;
    border: 1px solid #e0e0e0;
    border-radius: 4px;
    padding: 5px;
    min-width: 200px;
    min-height: 30px;
}

QDateEdit {
    background-color: #ffffff;
    color: #333333;
    border: 1px solid #e0e0e0;
    border-radius: 4px;
    padding: 5px;
    min-width: 120px;
}

QLineEdit:focus, QDateTimeEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border: 1px solid #2196F3;
}

/* Upload Areas */
QWidget[dragTarget="true"] {
    border: 2px dashed #2196F3;
    border-radius: 5px;
    padding: 5px;
    margin: 2px;
    background-color: #ffffff;
}

QWidget[dragTarget="true"]:hover {
    background-color: #e3f2fd;
    border-color: #1976D2;
}

/* Labels */
QLabel {
    color: #333333;
}

/* Menu Bar */
QMenuBar {
    background-color: #f5f5f5;
    color: #333333;
}

QMenuBar::item {
    background-color: transparent;
    padding: 4px 10px;
}

QMenuBar::item:selected {
    background-color: #e0e0e0;
    color: #2196F3;
}

QMenu {
    background-color: #ffffff;
    border: 1px solid #e0e0e0;
}

QMenu::item {
    padding: 5px 20px;
}

QMenu::item:selected {
    background-color: #e3f2fd;
    color: #2196F3;
}

/* Log Viewer */
QTextEdit {
    background-color: #ffffff;
    color: #333333;
    border: 1px solid #e0e0e0;
    border-radius: 4px;
    padding: 5px;
    font-family: monospace;
}
"""

# Dark Theme
DARK_THEME = """
/* Main Window and Basic Widgets */
QMainWindow, QWidget {
    background-color: #1e1e1e;
    color: #ffffff;
}

/* Tab Widget and Sidebar */
QTabWidget {
    background: #252526;
    border: none;
}

QTabWidget::pane {
    border: none;
    background: #252526;
}

QTabWidget::tab-bar {
    alignment: left;
    left: 0;
    top: 5px;
}

QTabBar::tab {
    padding: 8px 20px;
    color: #cccccc;
    background: #2d2d2d;
    border: none;
    font-size: 13px;
    font-weight: bold;
    width: 120px;
    margin: 1px 0;
    text-align: center;
}

QTabBar::tab:selected {
    color: #ffffff;
    background: #1e1e1e;
    border-left: 4px solid #0078d4;
}

QTabBar::tab:hover:!selected {
    color: #ffffff;
    background: #3e3e3e;
}

/* Group Boxes */
QGroupBox {
    background-color: #252526;
    border: 2px solid #3e3e3e;
    border-radius: 6px;
    margin-top: 1ex;
    font-weight: bold;
    color: #ffffff;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 5px;
    color: #0078d4;
}

/* Buttons */
QPushButton {
    background-color: #0078d4;
    color: white;
    border: none;
    padding: 8px 16px;
    border-radius: 4px;
    min-width: 80px;
}

QPushButton:hover {
    background-color: #1e90ff;
}

QPushButton:pressed {
    background-color: #005fb8;
}

QPushButton:disabled {
    background-color: #4d4d4d;
}

/* Table Widget */
QTableWidget {
    background-color: #252526;
    alternate-background-color: #2d2d2d;
    color: #ffffff;
    gridline-color: #3e3e3e;
    selection-background-color: #0078d4;
    selection-color: white;
    border: 1px solid #3e3e3e;
}

QHeaderView::section {
    background-color: #2d2d2d;
    color: #ffffff;
    padding: 5px;
    border: none;
    border-right: 1px solid #3e3e3e;
    border-bottom: 1px solid #3e3e3e;
}

/* Scroll Bars */
QScrollBar:vertical {
    background: #2d2d2d;
    width: 12px;
    margin: 0;
}

QScrollBar::handle:vertical {
    background: #3e3e3e;
    min-height: 30px;
    border-radius: 6px;
}

QScrollBar::handle:vertical:hover {
    background: #4e4e4e;
}

QScrollBar:horizontal {
    background: #2d2d2d;
    height: 12px;
    margin: 0;
}

QScrollBar::handle:horizontal {
    background: #3e3e3e;
    min-width: 30px;
    border-radius: 6px;
}

QScrollBar::handle:horizontal:hover {
    background: #4e4e4e;
}

/* Text Inputs */
QLineEdit, QSpinBox, QDoubleSpinBox {
    background-color: #2d2d2d;
    color: #ffffff;
    border: 1px solid #3e3e3e;
    border-radius: 4px;
    padding: 5px;
}

QDateTimeEdit {
    background-color: #2d2d2d;
    color: #ffffff;
    border: 1px solid #3e3e3e;
    border-radius: 4px;
    padding: 5px;
    min-width: 200px;
}

QDateEdit {
    background-color: #2d2d2d;
    color: #ffffff;
    border: 1px solid #3e3e3e;
    border-radius: 4px;
    padding: 5px;
    min-width: 120px;
}

QLineEdit:focus, QDateTimeEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border: 1px solid #0078d4;
}

/* Upload Areas */
QWidget[dragTarget="true"] {
    border: 2px dashed #0078d4;
    border-radius: 5px;
    padding: 5px;
    margin: 2px;
    background-color: #252526;
}

QWidget[dragTarget="true"]:hover {
    background-color: #2d2d2d;
    border-color: #1e90ff;
}

/* Labels */
QLabel {
    color: #ffffff;
}

/* Menu Bar */
QMenuBar {
    background-color: #2d2d2d;
    color: #ffffff;
}

QMenuBar::item {
    background-color: transparent;
    padding: 4px 10px;
}

QMenuBar::item:selected {
    background-color: #3e3e3e;
    color: #0078d4;
}

QMenu {
    background-color: #2d2d2d;
    border: 1px solid #3e3e3e;
}

QMenu::item {
    padding: 5px 20px;
}

QMenu::item:selected {
    background-color: #3e3e3e;
    color: #0078d4;
}

/* Log Viewer */
QTextEdit {
    background-color: #1e1e1e;
    color: #ffffff;
    border: 1px solid #3e3e3e;
    border-radius: 4px;
    padding: 5px;
    font-family: monospace;
}
"""