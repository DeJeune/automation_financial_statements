from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                               QTableWidget, QTableWidgetItem, QPushButton,
                               QFileDialog, QGroupBox, QLabel, QMessageBox,
                               QHeaderView, QApplication, QScrollArea, QSplitter,
                               QDateEdit, QDateTimeEdit, QDoubleSpinBox, QTabWidget,
                               QTextEdit, QMenuBar, QMenu, QSizePolicy)
from PySide6.QtCore import Qt, QSize, Signal, QObject, QThread, QEvent, QDate, QDateTime, QTimer
from PySide6.QtGui import QColor, QDropEvent, QImage, QKeyEvent, QActionGroup
from pathlib import Path
import asyncio
import shutil
from typing import Any, Dict, List
from datetime import date, datetime
import json
from src.config.shift_config import ShiftConfig
from src.processors.excel_updater import ExcelUpdater
from src.processors.invoice_processor import InvoiceProcessor
from src.processors.table_processor import TableProcessor
from src.utils.logger import logger
from src.gui.components.preview import TablePreviewDialog, ImagePreviewDialog
from src.utils.theme_manager import ThemeManager
import pandas as pd
import platform

REQUIRED_IMAGE_CATEGORIES = [
    "国通1", "国通2"
]
REQUIRED_TABLE_CATEGORIES = [  # 必填表格
    "油品时间统计", "油品优惠", "加油明细",
]
OPTIONAL_TABLE_CATEGORIES = ["通联", "抖音"]  # 可选表格
OPTIONAL_IMAGE_CATEGORIES = ["团油", "货车帮", "滴滴加油"]  # 可选图片
ALLOWED_IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.tiff', '.bmp'}
ALLOWED_TABLE_EXTENSIONS = {'.xlsx', '.xls', '.csv'}


class FileProcessingSignals(QObject):
    processing_complete = Signal(dict, str)


class TableProcessingWorker(QThread):
    """Worker thread for processing table files"""
    finished = Signal(dict, str)  # (result, category)
    error = Signal(str, str)  # (error_message, category)

    def __init__(self, processor: TableProcessor, file_path: Path, category: str):
        super().__init__()
        self.processor = processor
        self.file_path = file_path
        self.category = category

    def run(self):
        """运行处理任务"""
        try:
            # 创建事件循环
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(
                self.processor.process_table(
                    self.file_path,
                    self.category,
                )
            )
            self.finished.emit(result, self.category)
        except Exception as e:
            logger.error(f"Error processing table {self.category}: {str(e)}")
            self.error.emit(str(e), self.category)
        finally:
            loop.close()


class ProcessingWorker(QThread):
    """Worker thread for processing images"""
    finished = Signal(dict, str)  # (result, category)
    error = Signal(str, str)  # (error_message, category)

    def __init__(self, processor: InvoiceProcessor, file_path: Path, category: str):
        super().__init__()
        self.processor = processor
        self.file_path = file_path
        self.category = category

    def run(self):
        """Run the processing task"""
        try:
            # Create event loop for async operations
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            try:
                # Run the async processing
                result = loop.run_until_complete(
                    self.processor.process_invoice(
                        self.file_path, self.category)
                )

                # Emit the result
                self.finished.emit(result, self.category)

            except Exception as e:
                logger.error(f"Error processing {self.category}: {str(e)}")
                self.error.emit(str(e), self.category)

            finally:
                # Clean up the event loop
                loop.stop()
                loop.close()

        except Exception as e:
            logger.error(
                f"Error in worker thread for {self.category}: {str(e)}")
            self.error.emit(str(e), self.category)


class ImageSaveWorker(QThread):
    """Worker thread for saving images"""
    finished = Signal(bool, str)  # (success, error_message)

    def __init__(self, image: QImage, file_path: Path, format_name: str):
        super().__init__()
        self.image = image
        self.file_path = file_path
        self.format_name = format_name

    def run(self):
        try:
            # 对于PNG格式，使用压缩级别90
            if self.format_name == 'PNG':
                success = self.image.save(
                    str(self.file_path), self.format_name, quality=90)
            else:
                success = self.image.save(
                    str(self.file_path), self.format_name, quality=95)

            if not success:
                self.finished.emit(False, "保存图片失败")
            else:
                self.finished.emit(True, "")
        except Exception as e:
            self.finished.emit(False, str(e))


class TableInitializationWorker(QThread):
    """Worker thread for initializing table processors"""
    finished = Signal(bool, str)  # (success, error_message)

    def __init__(self, file_path: Path, selected_date: date, selected_work_start_time: datetime,
                 selected_shift_time: datetime, gas_price: float):
        super().__init__()
        self.file_path = file_path
        self.selected_date = selected_date
        self.selected_work_start_time = selected_work_start_time
        self.selected_shift_time = selected_shift_time
        self.gas_price = gas_price
        self.table_processor = None
        self.processor = None

    def run(self):
        try:
            shift_config = ShiftConfig(
                self.selected_date,
                self.selected_work_start_time,
                self.selected_shift_time,
                self.gas_price
            )
            self.table_processor = TableProcessor(self.file_path, shift_config)
            self.processor = InvoiceProcessor(self.file_path, shift_config)
            self.finished.emit(True, "")
        except Exception as e:
            logger.error(f"Error initializing processors: {str(e)}")
            self.finished.emit(False, str(e))


class ExcelUpdateWorker(QThread):
    """Worker thread for applying updates to Excel workbook"""
    finished = Signal(bool, str)  # (success, error_message)

    def __init__(self, excel_updater: ExcelUpdater, pending_updates: List[Dict[str, Any]]):
        super().__init__()
        self.excel_updater = excel_updater
        self.pending_updates = pending_updates

    def run(self):
        try:
            self.excel_updater.apply_updates(self.pending_updates)
            self.excel_updater.save_workbook()
            logger.info("Successfully applied all updates and saved workbook")
            self.finished.emit(True, "")
        except Exception as e:
            error_msg = str(e)
            logger.error(
                f"Error applying updates or saving workbook: {error_msg}")
            self.finished.emit(False, error_msg)


class LogViewer(QWidget):
    """Log viewer widget for displaying application logs"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()
        self.log_update_timer = QTimer(self)
        self.log_update_timer.timeout.connect(self.update_log)
        self.log_update_timer.start(1000)  # Update every second
        self.last_position = 0

    def init_ui(self):
        layout = QVBoxLayout(self)

        # Create log text area
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setLineWrapMode(QTextEdit.NoWrap)
        self.log_text.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #ffffff;
                font-family: 'Courier New', monospace;
                font-size: 12px;
            }
        """)

        # Add clear button
        clear_btn = QPushButton("清除日志")
        clear_btn.clicked.connect(self.clear_log)

        layout.addWidget(self.log_text)
        layout.addWidget(clear_btn)

    def update_log(self):
        """Update log content from the log file"""
        try:
            log_file = Path("logs/app.log")
            if not log_file.exists():
                return

            with open(log_file, 'r', encoding='utf-8') as f:
                f.seek(self.last_position)
                new_content = f.read()
                if new_content:
                    self.log_text.append(new_content)
                    self.last_position = f.tell()
                    # Scroll to bottom
                    scrollbar = self.log_text.verticalScrollBar()
                    scrollbar.setValue(scrollbar.maximum())
        except Exception as e:
            print(f"Error updating log: {str(e)}")

    def clear_log(self):
        """Clear the log viewer"""
        self.log_text.clear()


class MainWindow(QMainWindow):
    """Main window for the invoice processing application"""

    def __init__(self):
        super().__init__()
        # 添加操作系统判断
        self.is_windows = platform.system().lower() == 'windows'
        self.is_macos = platform.system().lower() == 'darwin'

        self.image_dir = Path("images")
        self.image_dir.mkdir(parents=True, exist_ok=True)
        self.table_dir = Path("tables")
        self.table_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir = Path("output/table")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.processor = None
        self.table_processor = None

        # Initialize theme manager
        self.theme_manager = ThemeManager()

        # Track uploaded files and their status
        self.uploaded_files: Dict[str, Path] = {}
        self.processing_status: Dict[str, str] = {}
        self.processing_results: Dict[str, dict] = {}
        self.pending_updates = []

        # 添加更新检查定时器
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self._check_and_apply_updates)
        self.update_timer.setInterval(500)  # 每500ms检查一次
        self.is_processing = False  # 标记是否正在处理文件

        # Initialize tracking dictionaries
        self.required_rows = {}
        self.optional_rows = {}
        self.required_table_rows = {}
        self.optional_table_rows = {}
        self.output_table_path = None

        # 添加日期和时间属性
        self.selected_date = QDate.currentDate()
        # Initialize with current date and time
        current_datetime = QDateTime.currentDateTime()
        self.selected_shift_time = current_datetime
        self.selected_work_start_time = current_datetime
        self.gas_price = 8.23  # Set a default positive value for gas price

        # 添加预览对话框引用
        self.preview_dialog = None

        # 添加拖放事件标志
        self.drag_acceptable = False

        self.init_ui()
        self.workers: List[ProcessingWorker] = []
        self.table_workers: List[TableProcessingWorker] = []
        # Enable clipboard monitoring
        self.clipboard = QApplication.clipboard()
        self.current_hover_category = None

    def init_ui(self):
        """Initialize the user interface"""
        self.setWindowTitle("发票处理系统")
        self.setMinimumSize(QSize(600, 400))

        # Create menu bar
        self._create_menu_bar()

        # Apply current theme
        self.apply_theme()

        # Create main horizontal splitter
        main_splitter = QSplitter(Qt.Horizontal)

        # Create tab widget for sidebar
        sidebar = QTabWidget()
        sidebar.setTabPosition(QTabWidget.West)  # Tabs on the left side

        # Create main content widget
        main_content = QWidget()
        main_layout = QVBoxLayout(main_content)
        main_layout.setContentsMargins(0, 0, 0, 0)  # Remove margins

        # Create vertical splitter for main content area
        content_splitter = QSplitter(Qt.Vertical)

        # Create scroll area for upload section
        upload_scroll = QScrollArea()
        upload_scroll.setWidgetResizable(True)
        upload_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarAlwaysOff)  # 禁用水平滚动条
        upload_widget = QWidget()
        upload_widget.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Preferred)  # 让widget能够水平扩展
        upload_layout = QVBoxLayout(upload_widget)
        upload_layout.setContentsMargins(10, 10, 10, 10)
        upload_layout.setSpacing(10)

        # Output table section
        output_group = QGroupBox("输出表格")
        output_group.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Preferred)  # 让GroupBox能够水平扩展
        output_layout = QVBoxLayout()
        output_layout.setContentsMargins(5, 5, 5, 5)
        output_layout.setSpacing(5)

        # Create table upload row
        table_row = QWidget()
        table_row.setAcceptDrops(True)
        table_row.setProperty("dragTarget", True)
        table_row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        row_layout = QHBoxLayout(table_row)
        row_layout.setContentsMargins(10, 5, 10, 5)
        row_layout.setSpacing(5)  # 添加组件间距

        # Add row content
        self.table_status_label = QLabel("拖放表格、点击上传或按Ctrl+V粘贴")
        self.table_status_label.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Preferred)  # 让状态标签能够自适应宽度
        self.table_status_label.setMinimumWidth(100)  # 减小最小宽度

        upload_table_btn = QPushButton("上传")
        upload_table_btn.setMinimumWidth(50)  # 减小按钮最小宽度
        upload_table_btn.setMaximumWidth(80)  # 限制最大宽度

        paste_table_btn = QPushButton("粘贴")
        paste_table_btn.setMinimumWidth(50)  # 减小按钮最小宽度
        paste_table_btn.setMaximumWidth(80)  # 限制最大宽度
        paste_table_btn.clicked.connect(
            lambda checked, c="output_table": self._handle_table_clipboard_paste(
                c)
        )

        # Set drag-and-drop events
        table_row.dragEnterEvent = lambda e: e.acceptProposedAction(
        ) if e.mimeData().hasUrls() else None
        table_row.dropEvent = lambda e, c="output_table": self._handle_table_drop(
            e, c)

        # Enable copy-paste support by installing event filter and registering the widget
        table_row.installEventFilter(self)
        # 修改行布局中组件的添加方式
        row_layout.addWidget(self.table_status_label, 1)  # 状态标签占用剩余空间
        row_layout.addWidget(paste_table_btn, 0)  # 按钮不拉伸
        row_layout.addWidget(upload_table_btn, 0)  # 按钮不拉伸

        output_layout.addWidget(table_row)
        output_group.setLayout(output_layout)
        upload_layout.addWidget(output_group)

        # Add date and time controls section
        date_time_group = QGroupBox("时间设置")
        date_time_layout = QVBoxLayout()  # Changed to QVBoxLayout for vertical arrangement

        # First row layout
        first_row_layout = QHBoxLayout()

        # Date selector
        date_label = QLabel("表格日期:")
        self.date_selector = QDateEdit()
        self.date_selector.setCalendarPopup(True)  # Enable calendar popup
        self.date_selector.setDate(self.selected_date)
        self.date_selector.dateChanged.connect(self._on_date_changed)

        # Work start time selector
        work_start_label = QLabel("上班时间:")
        self.work_start_selector = QDateTimeEdit()
        self.work_start_selector.setDisplayFormat(
            "yyyy-MM-dd HH:mm:ss")  # Show full date and time
        self.work_start_selector.setDateTime(
            QDateTime(self.selected_date, self.selected_work_start_time.time()))
        self.work_start_selector.dateTimeChanged.connect(
            self._on_work_start_time_changed)

        # Add first row widgets
        first_row_layout.addWidget(date_label)
        first_row_layout.addWidget(self.date_selector)
        first_row_layout.addSpacing(20)  # Add some space between controls
        first_row_layout.addWidget(work_start_label)
        first_row_layout.addWidget(self.work_start_selector)
        first_row_layout.addStretch()  # Add stretch to push controls to the left

        # Second row layout
        second_row_layout = QHBoxLayout()

        # Shift time selector
        shift_time_label = QLabel("交班时间:")
        self.shift_time_selector = QDateTimeEdit()
        self.shift_time_selector.setDisplayFormat(
            "yyyy-MM-dd HH:mm:ss")  # Show full date and time
        self.shift_time_selector.setDateTime(
            QDateTime(self.selected_date, self.selected_shift_time.time()))
        self.shift_time_selector.dateTimeChanged.connect(
            self._on_shift_time_changed)

        # Add gas price input
        gas_price_label = QLabel("#92汽油价格:")
        self.gas_price_input = QDoubleSpinBox()
        self.gas_price_input.setRange(0.01, 10000.00)  # Minimum value of 0.01
        self.gas_price_input.setDecimals(2)  # Show 2 decimal places
        self.gas_price_input.setSingleStep(0.01)  # Step by 0.01
        self.gas_price_input.setValue(self.gas_price)  # Set initial value
        self.gas_price_input.valueChanged.connect(self._on_gas_price_changed)

        # Add second row widgets
        second_row_layout.addWidget(shift_time_label)
        second_row_layout.addWidget(self.shift_time_selector)
        second_row_layout.addSpacing(20)  # Add some space between controls
        second_row_layout.addWidget(gas_price_label)
        second_row_layout.addWidget(self.gas_price_input)
        second_row_layout.addStretch()  # Add stretch to push controls to the left

        # Add both rows to the main date_time_layout
        date_time_layout.addLayout(first_row_layout)
        date_time_layout.addLayout(second_row_layout)

        date_time_group.setLayout(date_time_layout)
        upload_layout.addWidget(date_time_group)

        # Required files section
        required_group = QGroupBox("必填图片（必须全部上传）")
        required_layout = QVBoxLayout()

        for category in REQUIRED_IMAGE_CATEGORIES:
            row_widget = QWidget()
            row_widget.setAcceptDrops(True)
            row_widget.setSizePolicy(
                QSizePolicy.Expanding, QSizePolicy.Preferred)

            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(10, 5, 10, 5)
            row_layout.setSpacing(5)  # 添加组件间距

            category_label = QLabel(category)
            category_label.setMinimumWidth(50)  # 减小最小宽度
            category_label.setMaximumWidth(80)  # 限制最大宽度

            status_label = QLabel("拖放图片、点击上传或按Ctrl+V粘贴")
            status_label.setSizePolicy(
                QSizePolicy.Expanding, QSizePolicy.Preferred)
            status_label.setMinimumWidth(100)  # 减小最小宽度

            upload_btn = QPushButton("上传")
            upload_btn.setMinimumWidth(50)
            upload_btn.setMaximumWidth(80)

            paste_btn = QPushButton("粘贴")
            paste_btn.setMinimumWidth(50)
            paste_btn.setMaximumWidth(80)
            paste_btn.clicked.connect(
                lambda checked, c=category: self._handle_clipboard_paste(c)
            )

            row_widget.dropEvent = lambda e, c=category: self._handle_row_drop(
                e, c)

            # 修改行布局中组件的添加方式
            row_layout.addWidget(category_label, 0)  # 类别标签不拉伸
            row_layout.addWidget(status_label, 1)  # 状态标签占用剩余空间
            row_layout.addWidget(paste_btn, 0)  # 按钮不拉伸
            row_layout.addWidget(upload_btn, 0)  # 按钮不拉伸

            required_layout.addWidget(row_widget)
            self.required_rows[category] = (row_widget, status_label)

        required_group.setLayout(required_layout)
        upload_layout.addWidget(required_group)

        # 必填表格部分
        required_table_group = QGroupBox("必填表格（必须全部上传）")
        required_table_layout = QVBoxLayout()
        for category in REQUIRED_TABLE_CATEGORIES:
            # 创建表格上传行（与图片不同的样式）
            # 创建整行widget作为拖放区域
            row_widget = QWidget()
            row_widget.setAcceptDrops(True)
            row_widget.setSizePolicy(
                QSizePolicy.Expanding, QSizePolicy.Preferred)
            row_widget.setStyleSheet("""
                QWidget {
                    border: 2px dashed #aaa;
                    border-radius: 5px;
                    padding: 5px;
                    margin: 2px;
                }
                QWidget[dragTarget="true"] {
                    background-color: #e0f0e0;
                    border-color: #4CAF50;
                }
                QWidget:hover {
                    background-color: #f0f0f0;
                }
            """)

            # Enable focus and keyboard events
            row_widget.setFocusPolicy(Qt.StrongFocus)

            # Add event filters for hover and keyboard events
            row_widget.installEventFilter(self)

            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(10, 5, 10, 5)

            # 添加行内容
            category_label = QLabel(category)
            category_label.setMinimumWidth(60)
            category_label.setSizePolicy(
                QSizePolicy.Preferred, QSizePolicy.Preferred)
            status_label = QLabel("拖放表格、点击上传或按Ctrl+V粘贴")
            status_label.setMinimumWidth(150)
            status_label.setSizePolicy(
                QSizePolicy.Preferred, QSizePolicy.Preferred)
            upload_btn = QPushButton("上传")
            upload_btn.setMinimumWidth(60)
            paste_btn = QPushButton("粘贴")
            paste_btn.setMinimumWidth(60)

            # 连接信号
            upload_btn.clicked.connect(
                lambda checked, c=category: self._upload_table_file(c)
            )
            paste_btn.clicked.connect(
                lambda checked, c=category: self._handle_table_clipboard_paste(
                    c)
            )

            # 设置拖放事件
            row_widget.dragEnterEvent = lambda e: e.acceptProposedAction(
            ) if e.mimeData().hasUrls() else None
            row_widget.dropEvent = lambda e, c=category: self._handle_row_drop(
                e, c)

            # 添加到布局
            row_layout.addWidget(category_label)
            row_layout.addWidget(status_label)  # 移除stretch=1
            row_layout.addStretch()  # 添加弹性空间
            row_layout.addWidget(paste_btn)
            row_layout.addWidget(upload_btn)

            required_table_layout.addWidget(row_widget)
            self.required_table_rows[category] = (row_widget, status_label)
        required_table_group.setLayout(required_table_layout)
        upload_layout.addWidget(required_table_group)

        # Optional files section
        optional_group = QGroupBox("可选文件")
        optional_layout = QVBoxLayout()

        # 可选表格
        for category in OPTIONAL_TABLE_CATEGORIES:
            """创建表格上传行（样式与图片不同）"""
            row_widget = QWidget()
            row_widget.setAcceptDrops(True)
            row_widget.setSizePolicy(
                QSizePolicy.Expanding, QSizePolicy.Preferred)
            row_widget.setStyleSheet("""
                QWidget {
                    border: 2px dashed #aaa;
                    border-radius: 5px;
                    padding: 5px;
                    margin: 2px;
                }
                QWidget[dragTarget="true"] {
                    background-color: #e0f0e0;
                    border-color: #4CAF50;
                }
                QWidget:hover {
                    background-color: #f0f0f0;
                }
            """)
            row_widget.setProperty("dragTarget", False)
            row_widget.setFocusPolicy(Qt.StrongFocus)
            row_widget.installEventFilter(self)
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(10, 5, 10, 5)
            category_label = QLabel(category)
            category_label.setMinimumWidth(60)
            category_label.setSizePolicy(
                QSizePolicy.Preferred, QSizePolicy.Preferred)
            status_label = QLabel("拖放表格、点击上传或按Ctrl+V粘贴")
            status_label.setMinimumWidth(150)
            status_label.setSizePolicy(
                QSizePolicy.Preferred, QSizePolicy.Preferred)
            upload_btn = QPushButton("上传")
            upload_btn.setMinimumWidth(60)
            paste_btn = QPushButton("粘贴")
            paste_btn.setMinimumWidth(60)
            upload_btn.clicked.connect(
                lambda _, c=category: self._upload_table_file(c)
            )
            paste_btn.clicked.connect(
                lambda _, c=category: self._handle_table_clipboard_paste(c)
            )
            row_widget.dragEnterEvent = lambda e: e.acceptProposedAction(
            ) if e.mimeData().hasUrls() else None
            row_widget.dropEvent = lambda e, c=category: self._handle_row_drop(
                e, c)
            row_layout.addWidget(category_label)
            row_layout.addWidget(status_label)  # 移除stretch=1
            row_layout.addStretch()  # 添加弹性空间
            row_layout.addWidget(paste_btn)
            row_layout.addWidget(upload_btn)

            optional_layout.addWidget(row_widget)
            self.optional_table_rows[category] = (row_widget, status_label)

        # 创建可选文件行
        for category in OPTIONAL_IMAGE_CATEGORIES:
            row_widget = QWidget()
            row_widget.setAcceptDrops(True)
            row_widget.setSizePolicy(
                QSizePolicy.Expanding, QSizePolicy.Preferred)
            row_widget.setStyleSheet("""
                QWidget {
                    border: 2px dashed #aaa;
                    border-radius: 5px;
                    padding: 5px;
                    margin: 2px;
                }
                QWidget[dragTarget="true"] {
                    background-color: #e0f0e0;
                    border-color: #4CAF50;
                }
                QWidget:hover {
                    background-color: #f0f0f0;
                }
            """)
            row_widget.setProperty("dragTarget", False)
            row_widget.setFocusPolicy(Qt.StrongFocus)
            row_widget.installEventFilter(self)

            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(10, 5, 10, 5)

            category_label = QLabel(category)
            category_label.setMinimumWidth(60)
            category_label.setSizePolicy(
                QSizePolicy.Preferred, QSizePolicy.Preferred)
            status_label = QLabel("拖放图片、点击上传或按Ctrl+V粘贴")
            status_label.setMinimumWidth(150)
            status_label.setSizePolicy(
                QSizePolicy.Preferred, QSizePolicy.Preferred)
            upload_btn = QPushButton("上传")
            upload_btn.setMinimumWidth(60)
            paste_btn = QPushButton("粘贴")
            paste_btn.setMinimumWidth(60)

            upload_btn.clicked.connect(
                lambda checked, c=category: self._upload_file(c, optional=True)
            )
            paste_btn.clicked.connect(
                lambda checked, c=category: self._handle_clipboard_paste(c)
            )

            row_widget.dragEnterEvent = lambda e: e.acceptProposedAction(
            ) if e.mimeData().hasUrls() else None
            row_widget.dropEvent = lambda e, c=category: self._handle_row_drop(
                e, c)

            row_layout.addWidget(category_label)
            row_layout.addWidget(status_label)  # 移除stretch=1
            row_layout.addStretch()  # 添加弹性空间
            row_layout.addWidget(paste_btn)
            row_layout.addWidget(upload_btn)

            optional_layout.addWidget(row_widget)
            self.optional_rows[category] = (row_widget, status_label)

        optional_group.setLayout(optional_layout)
        upload_layout.addWidget(optional_group)

        # Set upload scroll content
        upload_scroll.setWidget(upload_widget)

        # Create scroll area for results section
        results_scroll = QScrollArea()
        results_scroll.setWidgetResizable(True)
        results_widget = QWidget()
        results_layout = QVBoxLayout(results_widget)

        # Results table
        self.result_table = QTableWidget()
        self.result_table.setColumnCount(5)
        self.result_table.setHorizontalHeaderLabels([
            "文件类型", "文件名", "状态", "处理结果", "操作"
        ])

        # Set table properties
        header = self.result_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)

        # Process button
        process_btn = QPushButton("处理所有文件")
        process_btn.clicked.connect(self._process_all_files)

        # Add export button
        export_btn = QPushButton("导出表格")
        export_btn.clicked.connect(self._export_output_table)

        # Add reset button
        reset_btn = QPushButton("重置")
        reset_btn.clicked.connect(self._reset_all)

        # Create button layout
        button_layout = QHBoxLayout()
        button_layout.addWidget(process_btn)
        button_layout.addWidget(export_btn)
        button_layout.addWidget(reset_btn)

        # Add components to results layout
        results_layout.addWidget(self.result_table)
        results_layout.addLayout(button_layout)

        # Set results scroll content
        results_scroll.setWidget(results_widget)

        # Add scroll areas to content splitter
        content_splitter.addWidget(upload_scroll)
        content_splitter.addWidget(results_scroll)

        # Set equal sizes for content sections
        content_splitter.setSizes([self.height() // 2, self.height() // 2])

        # Add content splitter to main layout
        main_layout.addWidget(content_splitter)

        # Create log viewer
        log_viewer = LogViewer()

        # Add tabs to sidebar
        sidebar.addTab(main_content, "首页")
        sidebar.addTab(log_viewer, "日志")

        # Add widgets to main splitter
        main_splitter.addWidget(sidebar)

        # Set initial sizes (sidebar 20%, content 80%)
        main_splitter.setSizes(
            [int(self.width() * 0.8), int(self.width() * 0.2)])

        # Set central widget
        self.setCentralWidget(main_splitter)

    def _create_menu_bar(self):
        """Create the menu bar with theme switching options"""
        menubar = self.menuBar()

        # Settings menu
        settings_menu = menubar.addMenu("设置")

        # Theme submenu
        theme_menu = settings_menu.addMenu("主题")

        # Create theme actions
        theme_group = QActionGroup(self)
        theme_group.setExclusive(True)

        # Light theme action
        light_theme_action = theme_menu.addAction("浅色主题")
        light_theme_action.setCheckable(True)
        light_theme_action.setActionGroup(theme_group)

        # Dark theme action
        dark_theme_action = theme_menu.addAction("深色主题")
        dark_theme_action.setCheckable(True)
        dark_theme_action.setActionGroup(theme_group)

        # Set current theme
        current_theme = self.theme_manager.get_current_theme()
        if current_theme == 'light':
            light_theme_action.setChecked(True)
        else:
            dark_theme_action.setChecked(True)

        # Connect theme actions
        light_theme_action.triggered.connect(
            lambda: self.change_theme('light'))
        dark_theme_action.triggered.connect(lambda: self.change_theme('dark'))

    def change_theme(self, theme):
        """Change the application theme"""
        self.theme_manager.set_theme(theme)
        self.apply_theme()

    def apply_theme(self):
        """Apply the current theme to the application"""
        style = self.theme_manager.get_theme_style()
        self.setStyleSheet(style)

    def _normalize_path(self, path_str: str) -> str:
        """根据操作系统规范化路径"""
        if self.is_windows:
            return path_str.replace('\\', '/')
        return path_str

    def _handle_table_drop(self, event: QDropEvent, category: str):
        """处理表格文件拖放事件"""
        try:
            urls = event.mimeData().urls()
            if urls and self.drag_acceptable:
                file_path = Path(self._normalize_path(urls[0].toLocalFile()))
                self._handle_table_upload(file_path, category)
                event.accept()
        except Exception as e:
            logger.error(f"表格拖放错误: {str(e)}")
            QMessageBox.critical(self, "错误", f"处理拖放失败: {str(e)}")
            event.ignore()

    def _handle_table_upload(self, file_path: Path, category: str):
        """处理表格文件验证和存储"""
        try:
            if file_path.suffix.lower() not in ALLOWED_TABLE_EXTENSIONS:
                QMessageBox.warning(self, "错误", "不支持的表格文件类型，请上传Excel或CSV文件")
                return

            # 更新状态为处理中
            if category == "output_table":
                status_label = self.table_status_label
            else:
                _, status_label = self.required_table_rows.get(
                    category) or self.optional_table_rows.get(category)

            if status_label:
                status_label.setText("处理中...")
            QApplication.processEvents()  # 确保UI更新

            # 删除之前的文件（如果存在）
            if category in self.uploaded_files:
                old_file = self.uploaded_files[category]
                try:
                    if old_file.exists():
                        old_file.unlink()
                except Exception as e:
                    logger.error(f"删除旧文件失败: {str(e)}")

            # 根据类别决定文件名和目标路径
            if category == "output_table":
                # 输出表格保持原始文件名
                dest_path = self.output_dir / file_path.name
            else:
                # 其他表格添加时间戳
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                new_filename = f"{category}_{timestamp}{file_path.suffix}"
                dest_path = self.table_dir / new_filename

            # Copy file to destination directory
            shutil.copy2(file_path, dest_path)

            # Update tracking for all categories (including output_table)
            self.uploaded_files[category] = dest_path
            self.processing_status[category] = "已上传"
            self.processing_results[category] = {}  # Initialize empty results

            # 如果是输出表格，在后台初始化TableProcessor
            if category == "output_table":
                try:
                    # Close existing workbooks if they exist
                    if self.processor and hasattr(self.processor, 'excel_updater'):
                        self.processor.excel_updater.close_workbook()
                    if self.table_processor and hasattr(self.table_processor, 'excel_updater'):
                        self.table_processor.excel_updater.close_workbook()

                    self.output_table_path = dest_path

                    # Create and start initialization worker
                    self.init_worker = TableInitializationWorker(
                        dest_path,
                        self.selected_date.toPython(),
                        self.selected_work_start_time.toPython(),
                        self.selected_shift_time.toPython(),
                        self.gas_price
                    )

                    # Connect signals
                    self.init_worker.finished.connect(
                        self._handle_initialization_complete)

                    # Update status
                    if status_label:
                        status_label.setText("正在初始化...")

                    # Start worker
                    self.init_worker.start()

                except Exception as e:
                    logger.error(f"Error starting initialization: {str(e)}")
                    if status_label:
                        status_label.setText("初始化失败")
                    QMessageBox.critical(self, "错误", f"初始化表格处理器失败: {str(e)}")
                    return

            # 更新状态标签
            if status_label and category != "output_table":
                status_label.setText("已上传")

            self._update_table()

        except Exception as e:
            logger.error(f"处理表格文件错误: {str(e)}")
            if status_label:
                status_label.setText("处理失败")
            QMessageBox.critical(self, "错误", f"表格文件处理失败: {str(e)}")

    def _handle_initialization_complete(self, success: bool, error_message: str):
        """Handle completion of table processor initialization"""
        try:
            if success:
                # Get the processors from the worker
                self.table_processor = self.init_worker.table_processor
                self.processor = self.init_worker.processor

                # Update status
                self.table_status_label.setText("已上传")
                logger.info("Successfully initialized table processors")
            else:
                self.table_status_label.setText("初始化失败")
                QMessageBox.critical(
                    self, "错误", f"初始化表格处理器失败: {error_message}")
        except Exception as e:
            logger.error(
                f"Error in initialization completion handler: {str(e)}")
            self.table_status_label.setText("初始化失败")
            QMessageBox.critical(self, "错误", f"处理初始化结果失败: {str(e)}")
        finally:
            # Clean up worker
            if hasattr(self, 'init_worker'):
                self.init_worker.quit()
                self.init_worker.wait()
                self.init_worker.deleteLater()

    def _handle_row_drop(self, event: QDropEvent, category: str):
        """处理整行拖放事件"""
        try:
            urls = event.mimeData().urls()
            if urls and self.drag_acceptable:
                file_path = Path(self._normalize_path(urls[0].toLocalFile()))
                # 根据类别和文件类型分别处理
                if category == "output_table" or category in REQUIRED_TABLE_CATEGORIES + OPTIONAL_TABLE_CATEGORIES:
                    if file_path.suffix.lower() not in ALLOWED_TABLE_EXTENSIONS:
                        QMessageBox.warning(
                            self, "错误", "不支持的表格文件类型，请上传Excel或CSV文件")
                        event.ignore()
                        return
                    self._handle_table_upload(file_path, category)
                else:
                    if file_path.suffix.lower() not in ALLOWED_IMAGE_EXTENSIONS:
                        QMessageBox.warning(
                            self, "错误", "不支持的图片文件类型，请上传JPG、PNG或BMP文件")
                        event.ignore()
                        return
                    self._handle_file_drop(category, file_path)
                event.accept()
        except Exception as e:
            logger.error(f"拖放错误: {str(e)}")
            QMessageBox.critical(self, "错误", f"处理拖放失败: {str(e)}")
            event.ignore()

    def _handle_file_drop(self, category: str, file_path: Path):
        """Handle image files dropped onto the widget"""
        try:
            if file_path.suffix.lower() not in ALLOWED_IMAGE_EXTENSIONS:
                QMessageBox.warning(self, "错误", "不支持的图片文件类型，请上传JPG、PNG或BMP文件")
                return

            # 删除之前的文件（如果存在）
            if category in self.uploaded_files:
                old_file = self.uploaded_files[category]
                try:
                    if old_file.exists():
                        old_file.unlink()
                except Exception as e:
                    logger.error(f"删除旧文件失败: {str(e)}")

            # Generate unique filename and save - preserve original extension
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            original_extension = file_path.suffix.lower()  # 保持原始扩展名
            new_filename = f"{category}_{timestamp}{original_extension}"
            dest_path = self.image_dir / new_filename

            # Copy file to destination
            shutil.copy2(file_path, dest_path)

            # Update tracking
            self.uploaded_files[category] = dest_path
            self.processing_status[category] = "已上传"

            # 获取对应的状态标签
            _, status_label = self.required_rows.get(
                category) or self.optional_rows.get(category)
            if status_label:
                status_label.setText("已上传")

            self._update_table()

        except Exception as e:
            logger.error(f"拖放图片文件错误: {str(e)}")
            QMessageBox.critical(self, "错误", f"图片文件处理失败: {str(e)}")

    def _upload_file(self, category: str, optional: bool = False) -> None:
        """Handle file upload for a specific category"""
        try:
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                f"选择{category}图片",
                "",
                # Changed order to put jpg first
                "Image Files (*.jpg *.jpeg *.png *.tiff *.bmp)"
            )

            if file_path:
                self._handle_file_drop(category, Path(file_path))

        except Exception as e:
            logger.error(f"上传文件错误: {str(e)}")
            QMessageBox.critical(self, "错误", f"上传失败: {str(e)}")

    def _process_all_files(self) -> None:
        """Process all uploaded files"""
        if not self._validate_required_files():
            QMessageBox.warning(self, "警告", "请先上传所有必选文件")
            return

        # Initialize pending updates list
        self.pending_updates = []
        self.is_processing = True  # 开始处理
        self.update_timer.start()  # 启动定时器
        try:
            # Check if workbook needs to be reopened
            if (hasattr(self.processor, 'excel_updater') and
                hasattr(self.table_processor, 'excel_updater') and
                (self.processor.excel_updater.workbook is None or
                    self.table_processor.excel_updater.workbook is None)):

                try:
                    # Reopen the workbook
                    self.processor.excel_updater.open_workbook(
                        self.output_table_path)
                    self.table_processor.excel_updater.open_workbook(
                        self.output_table_path)
                    logger.info("Successfully reopened Excel workbook")
                except Exception as e:
                    logger.error(f"Error reopening workbook: {str(e)}")
                    QMessageBox.critical(
                        self, "错误", f"重新打开Excel文件失败: {str(e)}")
                    return

            # Initialize pending updates list and start processing
            self.pending_updates = []
            self.is_processing = True
            self.update_timer.start()

            for category, file_path in self.uploaded_files.items():
                if self.processing_status[category] == "处理中" or category == "output_table":
                    continue

                if category in REQUIRED_TABLE_CATEGORIES + OPTIONAL_TABLE_CATEGORIES:
                    self._process_single_table(category, file_path)
                else:
                    self._process_single_image(category, file_path)

        except Exception as e:
            logger.error(f"Error in process_all_files: {str(e)}")
            QMessageBox.critical(self, "错误", f"处理文件时出错: {str(e)}")
            self.is_processing = False
            self.update_timer.stop()

    def _process_single_image(self, category: str, file_path: Path) -> None:
        """Process a single image file"""
        try:
            # Update status
            self.processing_status[category] = "处理中"
            self._update_table()

            # Create and start worker
            worker = ProcessingWorker(self.processor, file_path, category)
            worker.finished.connect(
                lambda result, cat: self._handle_processing_complete(
                    result, cat)
            )
            worker.error.connect(self._handle_processing_error)

            # Keep reference to prevent garbage collection
            self.workers.append(worker)
            worker.start()

        except Exception as e:
            logger.error(f"Error starting processing: {str(e)}")
            self._handle_processing_error(str(e), category)

    def _process_single_table(self, category: str, file_path: Path) -> None:
        """处理单个表格文件"""
        try:
            # Skip if it's output_table
            if category == "output_table":
                return

            # 更新状态
            self.processing_status[category] = "处理中"
            self._update_table()

            # 创建并启动工作线程
            worker = TableProcessingWorker(
                self.table_processor,
                file_path,
                category
            )

            # 连接信号并传递pending_updates列表
            worker.finished.connect(
                lambda result, cat: self._handle_table_processing_complete(
                    result, cat)
            )
            worker.error.connect(self._handle_processing_error)

            # 保持引用以防止垃圾回收
            self.table_workers.append(worker)
            worker.start()

        except Exception as e:
            logger.error(f"Error starting table processing: {str(e)}")
            self._handle_processing_error(str(e), category)

    def _handle_table_processing_complete(self, result: Dict, category: str) -> None:
        """Handle successful table processing completion"""
        try:
            # 保存处理结果
            self.processing_results[category] = result.get(
                'processed_data', {})

            # 将更新指令添加到待处理列表
            if 'updates' in result:
                self.pending_updates.extend(result['updates'])

            self.processing_status[category] = "完成"
            self._update_table()

        except Exception as e:
            logger.error(f"Error in table processing completion: {str(e)}")
            self._handle_processing_error(str(e), category)
        finally:
            # Remove worker
            self.table_workers = [
                w for w in self.table_workers if w.category != category]

    def _handle_processing_complete(self, result: Dict, category: str) -> None:
        """Handle successful processing completion"""
        try:
            # Store the processed data
            self.processing_results[category] = result.get(
                'processed_data', {})

            # Add updates to pending list if present
            if 'updates' in result:
                self.pending_updates.extend(result['updates'])

            self.processing_status[category] = "完成"
            self._update_table()

        except Exception as e:
            logger.error(f"Error in processing completion: {str(e)}")
            self._handle_processing_error(str(e), category)
        finally:
            # Remove worker
            self.workers = [w for w in self.workers if w.category != category]

    def _check_and_apply_updates(self) -> None:
        """
        检查是否所有处理都完成，如果完成则应用更新并停止定时器
        """
        if not self.is_processing:  # 如果没有正在进行的处理，直接返回
            self.update_timer.stop()
            return

        if self._check_all_processing_complete():
            self.is_processing = False  # 处理完成
            self.update_timer.stop()  # 停止定时器
            if self.pending_updates:  # 如果有待处理的更新
                logger.info(f"Applying {len(self.pending_updates)} updates")
                self._apply_all_updates()

    def _check_all_processing_complete(self) -> bool:
        """
        Check if all processing tasks are complete.
        Returns:
            bool: True if all tasks are complete, False otherwise
        """
        return all(
            self.processing_status.get(cat) == "完成"
            for cat in self.uploaded_files.keys()
            if cat != "output_table"
        )

    def _apply_all_updates(self) -> None:
        """
        Apply all pending updates to the workbook.
        This method should only be called when all processing is complete.
        """
        if not self.pending_updates:  # Skip if no updates to apply
            return

        try:
            # Update status to show we're updating the Excel file
            self.processing_status["output_table"] = "更新中"
            self._update_table()
            # Create and start the update worker
            self.update_worker = ExcelUpdateWorker(
                self.table_processor.excel_updater,
                self.pending_updates
            )
            self.update_worker.finished.connect(self._handle_update_complete)
            self.update_worker.start()

        except Exception as e:
            logger.error(f"Error starting update worker: {str(e)}")
            self.processing_status["output_table"] = "更新失败"
            self._update_table()
            QMessageBox.critical(self, "错误", f"启动表格更新失败: {str(e)}")

    def _handle_update_complete(self, success: bool, error_message: str) -> None:
        """Handle completion of Excel update operation"""
        try:
            if success:
                self.processing_status["output_table"] = "已完成"
                # Clear pending updates after successful application
                self.pending_updates = []
            else:
                self.processing_status["output_table"] = "更新失败"
                QMessageBox.critical(self, "错误", f"更新和保存表格失败: {error_message}")
        except Exception as e:
            logger.error(f"Error in update completion handler: {str(e)}")
            self.processing_status["output_table"] = "更新失败"
        finally:
            # Clean up worker
            self._update_table()
            if hasattr(self, 'update_worker'):
                self.update_worker.quit()
                self.update_worker.wait()
                self.update_worker.deleteLater()

    def _handle_processing_error(self, error_message: str, category: str) -> None:
        """Handle processing error"""
        self.processing_status[category] = f"错误: {error_message}"
        self._update_table()

        # Remove worker
        self.workers = [w for w in self.workers if w.category != category]

    def _update_table(self) -> None:
        """Update the results table"""
        self.result_table.setRowCount(len(self.uploaded_files))

        for row, (category, file_path) in enumerate(self.uploaded_files.items()):
            # Category
            self.result_table.setItem(row, 0, QTableWidgetItem(category))

            # Filename - make it clickable
            filename_item = QTableWidgetItem(file_path.name)
            # Store file path for preview
            filename_item.setData(Qt.UserRole, str(file_path))
            filename_item.setForeground(
                QColor(0, 0, 255))  # Make it look clickable
            filename_item.setToolTip("点击预览图片")
            self.result_table.setItem(row, 1, filename_item)

            # Status
            status_item = QTableWidgetItem(
                self.processing_status.get(category, "未处理"))
            if "错误" in status_item.text():
                status_item.setBackground(QColor(255, 200, 200))
            elif status_item.text() == "完成":
                status_item.setBackground(QColor(200, 255, 200))
            self.result_table.setItem(row, 2, status_item)

            # Result
            result = self.processing_results.get(category, {})
            try:
                # Convert DataFrame to dict if present
                if isinstance(result, pd.DataFrame):
                    result = result.to_dict()
                # Convert numpy types to Python native types
                if result:
                    result = json.loads(json.dumps(
                        result, default=lambda x: x.item() if hasattr(x, 'item') else str(x)))

                # Format the result in a more readable way
                if isinstance(result, dict):
                    result_text = ""
                    for key, value in result.items():
                        # Format each key-value pair
                        if isinstance(value, dict):
                            # Handle nested dictionaries
                            result_text += f"{key}:\n"
                            for sub_key, sub_value in value.items():
                                result_text += f"  {sub_key}: {sub_value}\n"
                        else:
                            result_text += f"{key}: {value}\n"
                else:
                    result_text = str(result) if result else ""

            except Exception as e:
                logger.error(
                    f"Error converting result to readable format for category {category}: {str(e)}")
                result_text = str(result)

            # Create and configure the result item
            result_item = QTableWidgetItem(result_text)
            result_item.setTextAlignment(
                Qt.AlignTop | Qt.AlignLeft)  # Align text to top-left
            self.result_table.setItem(row, 3, result_item)

            # Adjust row height to show all content
            self.result_table.resizeRowToContents(row)

            # Action button
            if category in (REQUIRED_IMAGE_CATEGORIES + OPTIONAL_IMAGE_CATEGORIES):
                action_btn = QPushButton("重新上传")
                action_btn.clicked.connect(
                    lambda checked, c=category: self._upload_file(c))
                self.result_table.setCellWidget(row, 4, action_btn)
            elif category in (REQUIRED_TABLE_CATEGORIES + OPTIONAL_TABLE_CATEGORIES + ["output_table"]):
                action_btn = QPushButton("重新上传")
                action_btn.clicked.connect(
                    lambda checked, c=category: self._upload_table_file(c))
                self.result_table.setCellWidget(row, 4, action_btn)

        # Connect cell click event
        self.result_table.cellClicked.connect(self._handle_table_cell_click)

    def _handle_table_cell_click(self, row: int, column: int) -> None:
        """Handle table cell click to show preview"""
        if column == 1:  # Filename column
            item = self.result_table.item(row, column)
            if item:
                file_path = Path(item.data(Qt.UserRole))

                # 获取文件类型（从第一列）
                category_item = self.result_table.item(row, 0)
                if not category_item:
                    return

                category = category_item.text()

                # 检查文件是否存在
                if not file_path.exists():
                    QMessageBox.warning(self, "错误", f"文件不存在: {file_path}")
                    return

                try:
                    # 关闭之前的预览对话框（如果存在）
                    if self.preview_dialog is not None:
                        self.preview_dialog.close()
                        self.preview_dialog = None

                    # 根据文件类型选择不同的预览方式
                    if category == "output_table" or category in REQUIRED_TABLE_CATEGORIES + OPTIONAL_TABLE_CATEGORIES:
                        # 表格预览
                        if file_path.suffix.lower() in ALLOWED_TABLE_EXTENSIONS:
                            self.preview_dialog = TablePreviewDialog(
                                file_path, self)
                            self.preview_dialog.show()
                        else:
                            QMessageBox.warning(self, "错误", "不支持的表格文件类型")
                    elif category in REQUIRED_IMAGE_CATEGORIES + OPTIONAL_IMAGE_CATEGORIES:
                        # 图片预览
                        self.preview_dialog = ImagePreviewDialog(
                            file_path, self)
                        self.preview_dialog.show()
                except Exception as e:
                    print(f"Error accessing file: {str(e)}")
                    QMessageBox.critical(self, "错误", f"无法访问文件: {str(e)}")

    def _validate_required_files(self) -> bool:
        """验证所有必填文件和表格文件已上传"""
        has_required = all(
            category in self.uploaded_files for category in REQUIRED_IMAGE_CATEGORIES + REQUIRED_TABLE_CATEGORIES)
        has_table = self.output_table_path is not None
        if not has_table:
            QMessageBox.warning(self, "警告", "请先上传输出表格文件")
        return has_required and has_table

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        """Handle widget events for clipboard paste support"""
        # Check if the object is one of our upload widgets
        category = None
        # Check required image rows
        for cat, (widget, _) in self.required_rows.items():
            if obj == widget:
                category = cat
                break
        # Check optional image rows
        if not category:
            for cat, (widget, _) in self.optional_rows.items():
                if obj == widget:
                    category = cat
                    break
        # Check required table rows
        if not category:
            for cat, (widget, _) in self.required_table_rows.items():
                if obj == widget:
                    category = cat
                    break
        # Check optional table rows
        if not category:
            for cat, (widget, _) in self.optional_table_rows.items():
                if obj == widget:
                    category = cat
                    break

        if category:
            if event.type() == QEvent.Enter:
                self.current_hover_category = category
                obj.setProperty("hovered", True)
                obj.style().unpolish(obj)
                obj.style().polish(obj)
                _, status_label = (self.required_rows.get(category) or
                                   self.optional_rows.get(category) or
                                   self.required_table_rows.get(category) or
                                   self.optional_table_rows.get(category))

                # 获取剪贴板数据
                mime_data = self.clipboard.mimeData()

                # 检查是否为表格类别
                is_table_category = (category == "output_table" or
                                     category in REQUIRED_TABLE_CATEGORIES + OPTIONAL_TABLE_CATEGORIES)

                # 检查剪贴板内容类型
                has_valid_table = (mime_data.hasUrls() and any(Path(url.toLocalFile()).suffix.lower() in ALLOWED_TABLE_EXTENSIONS
                                                               for url in mime_data.urls())) or \
                    (mime_data.hasText() and Path(mime_data.text().strip()).exists() and
                     Path(mime_data.text().strip()).suffix.lower() in ALLOWED_TABLE_EXTENSIONS)

                has_valid_image = mime_data.hasImage() or \
                    (mime_data.hasUrls() and any(Path(url.toLocalFile()).suffix.lower() in ALLOWED_IMAGE_EXTENSIONS
                                                 for url in mime_data.urls())) or \
                    (mime_data.hasText() and Path(mime_data.text().strip()).exists() and
                     Path(mime_data.text().strip()).suffix.lower() in ALLOWED_IMAGE_EXTENSIONS)

                # 根据类别和剪贴板内容显示相应提示
                if is_table_category:
                    if has_valid_table:
                        status_label.setText("按Ctrl+V粘贴文件")
                    else:
                        status_label.setText("拖放表格、点击上传或按Ctrl+V粘贴")
                else:
                    if has_valid_image:
                        status_label.setText("按Ctrl+V粘贴文件")
                    else:
                        status_label.setText("拖放图片、点击上传或按Ctrl+V粘贴")
                return True

            elif event.type() == QEvent.Leave:
                self.current_hover_category = None
                obj.setProperty("hovered", False)
                obj.style().unpolish(obj)
                obj.style().polish(obj)
                _, status_label = (self.required_rows.get(category) or
                                   self.optional_rows.get(category) or
                                   self.required_table_rows.get(category) or
                                   self.optional_table_rows.get(category))
                # Check if file is already uploaded for this category
                if category in self.uploaded_files:
                    status_label.setText("已上传")
                else:
                    # 根据类别显示相应的默认提示文本
                    if category == "output_table" or category in REQUIRED_TABLE_CATEGORIES + OPTIONAL_TABLE_CATEGORIES:
                        status_label.setText("拖放表格、点击上传或按Ctrl+V粘贴")
                    else:
                        status_label.setText("拖放图片、点击上传或按Ctrl+V粘贴")
                return True

            elif event.type() == QEvent.KeyPress:
                key_event = QKeyEvent(event)
                if (key_event.key() == Qt.Key_V and
                    key_event.modifiers() == Qt.ControlModifier and
                        self.current_hover_category == category):  # Only paste if mouse is hovering
                    # Check if it's a table category
                    if category in REQUIRED_TABLE_CATEGORIES + OPTIONAL_TABLE_CATEGORIES:
                        self._handle_table_clipboard_paste(category)
                    else:
                        self._handle_clipboard_paste(category)
                    return True

        return super().eventFilter(obj, event)

    def _handle_table_clipboard_paste(self, category: str) -> None:
        """Handle clipboard paste event for table files"""
        try:
            mime_data = self.clipboard.mimeData()

            # 获取状态标签
            status_label = None
            for cat, (_, label) in {**self.required_table_rows, **self.optional_table_rows}.items():
                if cat == category:
                    status_label = label
                    break

            if mime_data.hasUrls():
                urls = mime_data.urls()
                if urls:
                    file_path = Path(
                        self._normalize_path(urls[0].toLocalFile()))
                    if file_path.suffix.lower() in ALLOWED_TABLE_EXTENSIONS:
                        self._handle_table_upload(file_path, category)
                        return
                    else:
                        QMessageBox.warning(self, "错误", "不支持的表格文件类型")
                        if status_label:
                            status_label.setText("不支持的文件类型")
                        return
            elif mime_data.hasText():
                text = mime_data.text().strip()
                if Path(self._normalize_path(text)).exists():
                    file_path = Path(self._normalize_path(text))
                    if file_path.suffix.lower() in ALLOWED_TABLE_EXTENSIONS:
                        self._handle_table_upload(file_path, category)
                        return
                    else:
                        QMessageBox.warning(self, "错误", "不支持的表格文件类型")
                        if status_label:
                            status_label.setText("不支持的文件类型")
                        return
            else:
                QMessageBox.warning(self, "错误", "剪贴板中没有有效的表格文件")
                if status_label:
                    status_label.setText("无有效文件")
        except Exception as e:
            error_msg = f"粘贴表格文件错误: {str(e)}"
            logger.error(error_msg)
            QMessageBox.critical(self, "错误", f"粘贴表格文件失败: {str(e)}")
            if status_label:
                status_label.setText("粘贴失败")

    def _handle_clipboard_paste(self, category: str) -> None:
        """Handle clipboard paste event for images"""
        try:
            mime_data = self.clipboard.mimeData()

            # 获取状态标签
            status_label = None
            for cat, (_, label) in {**self.required_rows, **self.optional_rows}.items():
                if cat == category:
                    status_label = label
                    break

            if mime_data.hasUrls():
                urls = mime_data.urls()
                if urls:
                    file_path = Path(
                        self._normalize_path(urls[0].toLocalFile()))
                    if file_path.suffix.lower() in ALLOWED_IMAGE_EXTENSIONS:
                        self._handle_file_drop(category, file_path)
                        return
                    else:
                        QMessageBox.warning(self, "错误", "不支持的图片文件类型")
                        if status_label:
                            status_label.setText("不支持的文件类型")
                        return
            elif mime_data.hasText():
                text = mime_data.text().strip()
                if Path(self._normalize_path(text)).exists():
                    file_path = Path(self._normalize_path(text))
                    if file_path.suffix.lower() in ALLOWED_IMAGE_EXTENSIONS:
                        self._handle_file_drop(category, file_path)
                        return
                    else:
                        QMessageBox.warning(self, "错误", "不支持的图片文件类型")
                        if status_label:
                            status_label.setText("不支持的文件类型")
                        return
            elif mime_data.hasImage():
                if status_label:
                    status_label.setText("正在处理图片...")
                QApplication.processEvents()

                image = QImage(mime_data.imageData())
                if not image.isNull():
                    # 检测图片格式
                    formats = mime_data.formats()

                    # 默认使用PNG格式
                    extension = '.png'
                    format_name = 'PNG'

                    if self.is_windows:
                        # Windows系统的格式检测
                        if 'image/png' in formats or 'PNG' in formats:
                            extension = '.png'
                            format_name = 'PNG'
                        elif 'image/jpeg' in formats or 'JPEG' in formats:
                            extension = '.jpg'
                            format_name = 'JPEG'
                        elif 'image/bmp' in formats or 'BMP' in formats:
                            extension = '.bmp'
                            format_name = 'BMP'
                    else:
                        # macOS系统的格式检测
                        if 'image/png' in formats:
                            extension = '.png'
                            format_name = 'PNG'
                        elif 'image/jpeg' in formats:
                            extension = '.jpg'
                            format_name = 'JPEG'
                        elif 'x-qt-image' in formats:
                            format_data = mime_data.data('x-qt-image')
                            if format_data.startswith(b'\x89PNG'):
                                extension = '.png'
                                format_name = 'PNG'
                            elif format_data.startswith(b'\xff\xd8\xff'):
                                extension = '.jpg'
                                format_name = 'JPEG'
                            elif format_data.startswith(b'GIF8'):
                                extension = '.gif'
                                format_name = 'GIF'
                            elif format_data.startswith(b'BM'):
                                extension = '.bmp'
                                format_name = 'BMP'

                    # 生成临时文件
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    temp_filename = f"{category}_{timestamp}{extension}"
                    temp_path = self.image_dir / temp_filename
                    temp_path.parent.mkdir(parents=True, exist_ok=True)

                    # 创建并配置保存线程
                    self.save_worker = ImageSaveWorker(
                        image, temp_path, format_name)
                    self.save_worker.finished.connect(
                        lambda success, error_msg: self._handle_save_complete(
                            success, error_msg, category, temp_path, status_label
                        )
                    )
                    self.save_worker.start()
                else:
                    QMessageBox.warning(self, "错误", "剪贴板中的图片无效")
                    if status_label:
                        status_label.setText("图片无效")
            else:
                QMessageBox.warning(self, "错误", "剪贴板中没有图片")
                if status_label:
                    status_label.setText("无图片数据")
        except Exception as e:
            error_msg = f"粘贴图片错误: {str(e)}"
            logger.error(error_msg)
            QMessageBox.critical(self, "错误", f"粘贴图片失败: {str(e)}")
            if status_label:
                status_label.setText("粘贴失败")

    def _handle_save_complete(self, success: bool, error_msg: str, category: str,
                              temp_path: Path, status_label: QLabel) -> None:
        """Handle image save completion"""
        if success:
            # 删除之前的文件（如果存在）
            if category in self.uploaded_files:
                old_file = self.uploaded_files[category]
                try:
                    if old_file.exists():
                        old_file.unlink()
                except Exception as e:
                    logger.error(f"删除旧文件失败: {str(e)}")

            self.uploaded_files[category] = temp_path
            self.processing_status[category] = "已上传"
            if status_label:
                status_label.setText("已上传")
            self._update_table()
        else:
            QMessageBox.critical(self, "错误", f"保存图片失败: {error_msg}")
            if status_label:
                status_label.setText("保存失败")

        # 清理工作线程
        if hasattr(self, 'save_worker'):
            self.save_worker.quit()
            self.save_worker.wait()
            self.save_worker.deleteLater()

    def _on_date_changed(self, new_date: QDate) -> None:
        """Handle date selection change"""
        self.selected_date = new_date
        # Update the date part of the time selectors while preserving their times
        self.work_start_selector.setDateTime(
            QDateTime(new_date, self.work_start_selector.time()))
        self.shift_time_selector.setDateTime(
            QDateTime(new_date, self.shift_time_selector.time()))

        # Update processors if output table exists
        if self.output_table_path and self.output_table_path.exists():
            self._update_processors_config()

    def _on_shift_time_changed(self, new_datetime: QDateTime) -> None:
        """Handle shift time selection change"""
        self.selected_shift_time = new_datetime
        # Update processors if output table exists
        if self.output_table_path and self.output_table_path.exists():
            self._update_processors_config()

    def _on_work_start_time_changed(self, new_datetime: QDateTime) -> None:
        """Handle work start time selection change"""
        self.selected_work_start_time = new_datetime
        # Update processors if output table exists
        if self.output_table_path and self.output_table_path.exists():
            self._update_processors_config()

    def _on_gas_price_changed(self, new_price: float) -> None:
        """Handle gas price change"""
        if new_price <= 0:
            QMessageBox.warning(self, "警告", "汽油价格必须大于0")
            self.gas_price_input.setValue(
                self.gas_price)  # Revert to previous value
            return
        self.gas_price = new_price
        # Update processors if output table exists
        if self.output_table_path and self.output_table_path.exists():
            self._update_processors_config()

    def _update_processors_config(self) -> None:
        """Update processors with new ShiftConfig"""
        try:
            # Create new ShiftConfig with current settings
            shift_config = ShiftConfig(
                self.selected_date.toPython(),
                self.selected_work_start_time.toPython(),
                self.selected_shift_time.toPython(),
                self.gas_price
            )

            # Update processors if they exist
            if self.table_processor:
                self.table_processor.shift_config = shift_config
            if self.processor:
                self.processor.shift_config = shift_config

            logger.info("Successfully updated processors configuration")
        except Exception as e:
            logger.error(f"Error updating processors configuration: {str(e)}")
            QMessageBox.critical(self, "错误", f"更新处理器配置失败: {str(e)}")

    def _perform_reset(self) -> None:
        """Perform the actual reset operations without confirmation dialog"""
        try:
            # Stop any ongoing processing
            self.is_processing = False
            self.update_timer.stop()

            # Close workbooks if processors exist
            if self.processor and hasattr(self.processor, 'excel_updater'):
                self.processor.excel_updater.close_workbook()
            if self.table_processor and hasattr(self.table_processor, 'excel_updater'):
                self.table_processor.excel_updater.close_workbook()

            # Reset processors
            self.processor = None
            self.table_processor = None

            # Delete uploaded files
            for file_path in self.uploaded_files.values():
                try:
                    if file_path.exists():
                        file_path.unlink()
                except Exception as e:
                    logger.error(f"Error deleting file {file_path}: {str(e)}")

            # Clear tracking dictionaries
            self.uploaded_files.clear()
            self.processing_status.clear()
            self.processing_results.clear()
            self.pending_updates.clear()
            self.output_table_path = None

            # Reset status labels
            for _, status_label in self.required_rows.values():
                status_label.setText("拖放图片、点击上传或按Ctrl+V粘贴")
            for _, status_label in self.optional_rows.values():
                status_label.setText("拖放图片、点击上传或按Ctrl+V粘贴")
            for _, status_label in self.required_table_rows.values():
                status_label.setText("拖放表格、点击上传或按Ctrl+V粘贴")
            for _, status_label in self.optional_table_rows.values():
                status_label.setText("拖放表格、点击上传或按Ctrl+V粘贴")
            self.table_status_label.setText("拖放表格、点击上传或按Ctrl+V粘贴")

            # Clear result table
            self.result_table.setRowCount(0)

            # Reset workers
            self.workers.clear()
            self.table_workers.clear()

            logger.info("Successfully reset all content")

        except Exception as e:
            logger.error(f"Error during reset: {str(e)}")
            QMessageBox.critical(self, "错误", f"重置过程中出错: {str(e)}")

    def closeEvent(self, event) -> None:
        """Handle application closing"""
        try:
            self.update_timer.stop()  # Stop timer
            # Perform reset operations to clean up files
            self._perform_reset()
            # Safely wait for update worker if it exists and is running
            if hasattr(self, 'update_worker'):
                try:
                    if self.update_worker.isRunning():
                        self.update_worker.wait()
                except RuntimeError as e:
                    logger.info(
                        "Update worker already deleted. Skipping wait.")
            event.accept()
        except Exception as e:
            logger.error(f"Error during application close: {str(e)}")
            event.accept()  # Still close the application even if there's an error

    def _reset_all(self) -> None:
        """Reset all uploaded files and UI state"""
        # Show confirmation dialog
        reply = QMessageBox.question(
            self,
            "确认重置",
            "确定要重置所有内容吗？这将清除所有已上传的文件。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply == QMessageBox.No:
            return

        self._perform_reset()
        QMessageBox.information(self, "成功", "已重置所有内容")

    def _export_output_table(self) -> None:
        """Export the output table to a user-specified location"""
        if not self.output_table_path or not self.output_table_path.exists():
            QMessageBox.warning(self, "警告", "没有可导出的表格文件")
            return

        try:
            # Get the destination path from user
            dest_path, _ = QFileDialog.getSaveFileName(
                self,
                "导出表格",
                # Use original filename as default
                str(self.output_table_path.name),
                "Excel Files (*.xlsx *.xls);;All Files (*.*)"
            )

            if dest_path:
                # Copy the file
                shutil.copy2(self.output_table_path, dest_path)
                QMessageBox.information(self, "成功", "表格导出成功")
        except Exception as e:
            logger.error(f"导出表格错误: {str(e)}")
            QMessageBox.critical(self, "错误", f"导出表格失败: {str(e)}")

    def _check_drag_data(self, mime_data, category: str) -> bool:
        """检查拖放数据是否有效"""
        if not mime_data.hasUrls():
            return False

        urls = mime_data.urls()
        if not urls:
            return False

        file_path = Path(self._normalize_path(urls[0].toLocalFile()))

        # 检查文件类型
        if category == "output_table" or category in REQUIRED_TABLE_CATEGORIES + OPTIONAL_TABLE_CATEGORIES:
            return file_path.suffix.lower() in ALLOWED_TABLE_EXTENSIONS
        else:
            return file_path.suffix.lower() in ALLOWED_IMAGE_EXTENSIONS
