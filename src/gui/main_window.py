from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                               QTableWidget, QTableWidgetItem, QPushButton,
                               QFileDialog, QGroupBox, QLabel, QMessageBox,
                               QHeaderView, QApplication, QScrollArea, QSplitter,
                               QDateEdit, QDateTimeEdit, QDoubleSpinBox, QTabWidget,
                               QTextEdit, QSizePolicy, QFrame, QLineEdit)
from PySide6.QtCore import QSize, Qt, Signal, QObject, QThread, QEvent, QDate, QDateTime, QTimer
from PySide6.QtGui import QColor, QDropEvent, QImage, QKeyEvent, QActionGroup
from pathlib import Path
import asyncio
import shutil
from typing import Any, Dict, List
from datetime import date, datetime
from dataclasses import replace
import json
from src.config.shift_config import ShiftConfig
from src.processors.excel_updater import ExcelUpdater
from src.processors.invoice_processor import InvoiceProcessor
from src.processors.table_processor import TableProcessor
from src.utils.logger import logger
from src.utils.app_paths import get_log_file_path, get_runtime_subdir
from src.gui.components.preview import TablePreviewDialog, ImagePreviewDialog
from src.utils.theme_manager import ThemeManager
from typing import cast
import pandas as pd
import openpyxl
from src.processors.simple_report import (
    SimpleReportProcessor, SIMPLE_CATEGORIES, SIMPLE_REQUIRED_CATEGORIES, is_simple_report,
)
import platform

REQUIRED_IMAGE_CATEGORIES: list[str] = []
REQUIRED_TABLE_CATEGORIES = [  # 必填表格
    "油品时间统计", "油品优惠", "加油明细", "充值明细"
]
OPTIONAL_TABLE_CATEGORIES = ["油品时间统计(调价后)", "通联"]  # 可选表格
OPTIONAL_IMAGE_CATEGORIES = ["国通1", "国通2", "团油", "货车帮", "滴滴加油", "POS", "超市销售收入", "抖音"]  # 可选图片
TEMPLATE_LABELS = {'output_table': '日报模板', 'simple_output_table': '简表模板'}
ALLOWED_IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.tiff', '.bmp'}
ALLOWED_TABLE_EXTENSIONS = {'.xlsx', '.xls', '.csv'}


class WorkerSignals(QObject):
    """Defines the signals available from a running worker thread."""
    finished = Signal(dict, str)  # (result, category)
    error = Signal(str, str)  # (error_message, category)


class TableProcessingWorker(QThread):
    """Worker for processing table files"""
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


class SimpleReportWorker(QThread):
    """Read and reconcile source exports before scheduling any workbook writes."""
    finished = Signal(dict, str)
    error = Signal(str, str)

    def __init__(self, processor: SimpleReportProcessor, paths: Dict[str, Path]):
        super().__init__()
        self.processor = processor
        self.paths = paths

    def run(self):
        try:
            self.finished.emit(self.processor.build_updates(self.paths), 'simple_output_table')
        except Exception as error:
            self.error.emit(str(error), 'simple_output_table')


class ProcessingWorker(QThread):
    """Worker for processing images"""
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
                    str(self.file_path), quality=90)
            else:
                success = self.image.save(
                    str(self.file_path), quality=95)

            if not success:
                self.finished.emit(False, "保存图片失败")
            else:
                self.finished.emit(True, "")
        except Exception as e:
            self.finished.emit(False, str(e))


class ExcelUpdateWorker(QThread):
    """Worker thread for applying updates to Excel workbook"""
    finished = Signal(bool, str)  # (success, error_message)

    def __init__(self, output_table_path: Path, pending_updates: List[Dict[str, Any]]):
        super().__init__()
        self.output_table_path = output_table_path
        self.pending_updates = pending_updates

    def run(self):
        """Run the update operation in the worker thread"""
        updater = None
        try:
            # Initialize ExcelUpdater in the worker thread
            updater = ExcelUpdater(self.output_table_path)
            updater.apply_updates(self.pending_updates)
            updater.save_workbook()
            logger.info("Successfully applied updates to workbook")
            self.finished.emit(True, "")
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error applying updates: {error_msg}")
            self.finished.emit(False, error_msg)
        finally:
            if updater is not None:
                updater.close_workbook()


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
        self.log_text.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
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
            log_file = get_log_file_path()
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


class NoScrollDateEdit(QDateEdit):
    """Custom QDateEdit that ignores mouse wheel events"""
    def wheelEvent(self, event):
        event.ignore()


class NoScrollDateTimeEdit(QDateTimeEdit):
    """Custom QDateTimeEdit that ignores mouse wheel events"""
    def wheelEvent(self, event):
        event.ignore()




class MainWindow(QMainWindow):
    """Main window for the invoice processing application"""

    # Define signal at class level
    processing_completed = Signal()

    def __init__(self):
        super().__init__()

        # Initialize active workers list and counter
        self.files_to_process = 0

        # Connect the signal
        self.processing_completed.connect(self._on_all_processing_complete)

        # 在初始化时设置默认字体和编码
        if platform.system().lower() == 'windows':
            self.is_windows = True
            self.is_mac = False
        else:
            self.is_mac = True
            self.is_windows = False

        self.image_dir = get_runtime_subdir("images")
        self.table_dir = get_runtime_subdir("tables")
        self.output_dir = get_runtime_subdir("output", "table")

        # Initialize theme manager
        self.theme_manager = ThemeManager()

        # Track uploaded files and their status
        self.uploaded_files: Dict[str, List[Path]] = {}
        self.processing_status: Dict[str, str] = {}
        self.processing_results: Dict[str, dict] = {}
        self.pending_updates = []

        # Accumulation tracking for multi-image categories
        self._category_pending_count: Dict[str, int] = {}
        self._category_partial_results: Dict[str, List[dict]] = {}

        self.active_workers: List[QThread] = []

        # Create menu bar before initializing UI
        self.menubar = self.menuBar()

        # Initialize tracking dictionaries
        self.required_rows = {}
        self.optional_rows = {}
        self.required_table_rows = {}
        self.optional_table_rows = {}
        self.output_table_path = None
        self.simple_output_table_path = None
        self.simple_report = False
        self.template_rows = {}
        self.simple_pending_updates = []
        self.update_workers = {}
        self.failed_outputs = set()

        # Initialize with current date and time
        current_datetime = QDateTime.currentDateTime()
        current_date = QDate.currentDate()
        current_dt = current_datetime.toPython()
        self.shift_config = ShiftConfig(
            date= date(current_date.year(), current_date.month(), current_date.day()),
            work_start_time=cast(datetime, current_dt),
            shift_time=cast(datetime, current_dt),
            gas_price=8.23
        )

        # 添加预览对话框引用
        self.preview_dialog = None
        self.init_ui()
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
        main_splitter = QSplitter(Qt.Orientation.Horizontal)

        # Create tab widget for sidebar
        sidebar = QTabWidget()
        sidebar.setTabPosition(QTabWidget.TabPosition.North)

        # Create main content widget
        main_content = QWidget()
        main_layout = QVBoxLayout(main_content)
        main_layout.setContentsMargins(0, 0, 0, 0)  # Remove margins

        # Create vertical splitter for main content area
        content_splitter = QSplitter(Qt.Orientation.Vertical)

        # Create scroll area for upload section
        upload_scroll = QScrollArea()
        upload_scroll.setWidgetResizable(True)
        upload_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)  # 禁用水平滚动条
        upload_widget = QWidget()
        upload_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)  # 让widget能够水平扩展
        upload_layout = QVBoxLayout(upload_widget)
        upload_layout.setContentsMargins(10, 10, 10, 10)
        upload_layout.setSpacing(10)

        # Independent template slots share source uploads, never the output file.
        for category, title in TEMPLATE_LABELS.items():
            group = QGroupBox(title)
            layout = QVBoxLayout(group)
            row = QWidget()
            row.setAcceptDrops(True)
            row.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            row.installEventFilter(self)
            row_layout = QHBoxLayout(row)
            status = QLabel('拖放模板、点击上传或按 Ctrl+V 粘贴')
            status.setWordWrap(True)
            row_layout.addWidget(status, 1)
            for text, callback in [
                ('粘贴', lambda checked=False, c=category: self._handle_clipboard_paste(c)),
                ('上传模板', lambda checked=False, c=category: self._upload_table_file(c)),
                ('清除', lambda checked=False, c=category: self._clear_category(c)),
            ]:
                button = QPushButton(text)
                button.clicked.connect(callback)
                row_layout.addWidget(button)
            row.dragEnterEvent = lambda event: event.acceptProposedAction() if event.mimeData().hasUrls() else None
            row.dropEvent = lambda event, c=category: self._handle_row_drop(event, c)
            self.template_rows[category] = (row, status)
            layout.addWidget(row)
            upload_layout.addWidget(group)
        self.table_status_label = self.template_rows['output_table'][1]

        # Add date and time controls section
        date_time_group = QGroupBox("时间设置")
        date_time_layout = QVBoxLayout()  # Changed to QVBoxLayout for vertical arrangement

        # First row layout
        first_row_layout = QHBoxLayout()

        # Date selector
        date_label = QLabel("表格日期:")
        self.date_selector = NoScrollDateEdit()  # Use custom widget
        self.date_selector.setCalendarPopup(True)
        self.date_selector.setDate(self.shift_config.date)  # type: ignore[arg-type]
        self.date_selector.dateChanged.connect(self._on_date_changed)

        # Work start time selector
        work_start_label = QLabel("上班时间:")
        self.work_start_selector = NoScrollDateTimeEdit()  # Use custom widget
        self.work_start_selector.setDisplayFormat(self._get_datetime_format())
        self.work_start_selector.setDateTime(self.shift_config.work_start_time)  # type: ignore[arg-type]
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
        self.shift_time_selector = NoScrollDateTimeEdit()  # Use custom widget
        self.shift_time_selector.setDisplayFormat(self._get_datetime_format())
        self.shift_time_selector.setDateTime(self.shift_config.shift_time)  # type: ignore[arg-type]
        self.shift_time_selector.dateTimeChanged.connect(
            self._on_shift_time_changed)

        # Add gas price input
        gas_price_label = QLabel("#92汽油价格:")
        self.gas_price_input = QDoubleSpinBox()
        self.gas_price_input.setRange(0.01, 10000.00)  # Minimum value of 0.01
        self.gas_price_input.setDecimals(2)  # Show 2 decimal places
        self.gas_price_input.setSingleStep(0.01)  # Step by 0.01
        self.gas_price_input.setValue(
            self.shift_config.gas_price)  # Set initial value
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

        self.simple_options = QWidget()
        simple_layout = QHBoxLayout(self.simple_options)
        self.simple_divisor = QDoubleSpinBox()
        self.simple_divisor.setRange(1, 100)
        self.simple_divisor.setValue(3)
        self.simple_count_divisor = QDoubleSpinBox()
        self.simple_count_divisor.setRange(1, 100)
        self.simple_count_divisor.setValue(3)
        simple_layout.addWidget(QLabel('简表金额/升数除以：'))
        simple_layout.addWidget(self.simple_divisor)
        simple_layout.addWidget(QLabel('次数除以：'))
        simple_layout.addWidget(self.simple_count_divisor)
        self.simple_closing_balance = QLineEdit()
        self.simple_closing_balance.setPlaceholderText('可选，填截图中期末余额的合计')
        simple_layout.addWidget(QLabel('新系统卡余额合计：'))
        simple_layout.addWidget(self.simple_closing_balance)
        self.simple_options.hide()
        date_time_layout.addWidget(self.simple_options)
        self.simple_hint = QLabel(
            '简表需油品时间统计、加油明细、充值明细；油品优惠表可选。'
            '新系统卡期末余额合计由截图读取后输入，折算后填入 G8；Python 对照版不自动识别余额图片。'
            '未说明字段保留模板原值。请核对日期和折算除数。')
        self.simple_hint.setWordWrap(True)
        self.simple_hint.hide()
        date_time_layout.addWidget(self.simple_hint)

        date_time_group.setLayout(date_time_layout)
        upload_layout.addWidget(date_time_group)

        # 必填表格部分
        required_table_group = QGroupBox("必填表格（必须全部上传）")
        self.required_table_group = required_table_group
        required_table_layout = QVBoxLayout()
        required_table_layout.setSpacing(0)  # Set spacing to 0 to control spacing manually

        for i, category in enumerate(REQUIRED_TABLE_CATEGORIES):
            # 创建表格上传行（与图片不同的样式）
            # 创建整行widget作为拖放区域
            row_widget = QWidget()
            row_widget.setAcceptDrops(True)
            row_widget.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

            # Enable focus and keyboard events
            row_widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

            # Add event filters for hover and keyboard events
            row_widget.installEventFilter(self)

            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(10, 5, 10, 5)

            # 添加行内容
            category_label = QLabel(category)
            category_label.setMinimumWidth(60)
            category_label.setSizePolicy(
                QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
            status_label = QLabel("拖放表格、点击上传或按Ctrl+V粘贴")
            status_label.setMinimumWidth(150)
            status_label.setSizePolicy(
                QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
            upload_btn = QPushButton("上传")
            upload_btn.setMinimumWidth(60)
            paste_btn = QPushButton("粘贴")
            paste_btn.setMinimumWidth(60)

            # 连接信号
            upload_btn.clicked.connect(
                lambda checked, c=category: self._upload_table_file(c)
            )
            paste_btn.clicked.connect(
                lambda checked, c=category: self._handle_clipboard_paste(
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
            # Add separator line if not the last item
            if i < len(REQUIRED_TABLE_CATEGORIES) - 1:
                required_table_layout.addWidget(self._create_separator())

        required_table_group.setLayout(required_table_layout)
        upload_layout.addWidget(required_table_group)

        # Optional files section
        optional_group = QGroupBox("可选文件")
        optional_layout = QVBoxLayout()
        optional_layout.setSpacing(0)  # Set spacing to 0 to control spacing manually

        # 可选表格
        for category in OPTIONAL_TABLE_CATEGORIES:
            """创建表格上传行（样式与图片不同）"""
            row_widget = QWidget()
            row_widget.setAcceptDrops(True)
            row_widget.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

            row_widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            row_widget.installEventFilter(self)
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(10, 5, 10, 5)
            category_label = QLabel(category)
            category_label.setMinimumWidth(60)
            category_label.setSizePolicy(
                QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
            status_label = QLabel("拖放表格、点击上传或按Ctrl+V粘贴")
            status_label.setMinimumWidth(150)
            status_label.setSizePolicy(
                QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
            upload_btn = QPushButton("上传")
            upload_btn.setMinimumWidth(60)
            paste_btn = QPushButton("粘贴")
            paste_btn.setMinimumWidth(60)
            upload_btn.clicked.connect(
                lambda _, c=category: self._upload_table_file(c)
            )
            paste_btn.clicked.connect(
                lambda _, c=category: self._handle_clipboard_paste(c)
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

            # Add separator line after table categories except last one
            if category != OPTIONAL_TABLE_CATEGORIES[-1]:
                optional_layout.addWidget(self._create_separator())

        # Add a separator line between table and image sections if both exist
        if OPTIONAL_TABLE_CATEGORIES and OPTIONAL_IMAGE_CATEGORIES:
            optional_layout.addWidget(self._create_separator())

        # 创建可选文件行
        for i, category in enumerate(OPTIONAL_IMAGE_CATEGORIES):
            row_widget = QWidget()
            row_widget.setAcceptDrops(True)
            row_widget.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

            row_widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            row_widget.installEventFilter(self)

            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(10, 5, 10, 5)

            category_label = QLabel(category)
            category_label.setMinimumWidth(60)
            category_label.setSizePolicy(
                QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
            status_label = QLabel("拖放图片、点击上传或按Ctrl+V粘贴")
            status_label.setMinimumWidth(150)
            status_label.setSizePolicy(
                QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
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

            clear_btn = QPushButton("清除")
            clear_btn.setMinimumWidth(60)
            clear_btn.clicked.connect(
                lambda checked, c=category: self._clear_category(c)
            )

            row_layout.addWidget(category_label)
            row_layout.addWidget(status_label)  # 移除stretch=1
            row_layout.addStretch()  # 添加弹性空间
            row_layout.addWidget(paste_btn)
            row_layout.addWidget(upload_btn)
            row_layout.addWidget(clear_btn)

            optional_layout.addWidget(row_widget)
            self.optional_rows[category] = (row_widget, status_label)

            # Add separator line between image categories except last one
            if i < len(OPTIONAL_IMAGE_CATEGORIES) - 1:
                optional_layout.addWidget(self._create_separator())

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
        self.result_table.cellClicked.connect(self._handle_table_cell_click)

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
        export_btn = QPushButton("导出日报")
        export_btn.clicked.connect(lambda: self._export_output_table('output_table'))
        simple_export_btn = QPushButton("导出简表")
        simple_export_btn.clicked.connect(lambda: self._export_output_table('simple_output_table'))
        self.template_export_buttons = {'output_table': export_btn, 'simple_output_table': simple_export_btn}

        # Add reset button
        reset_btn = QPushButton("重置")
        reset_btn.clicked.connect(self._reset_all)

        # Create button layout
        button_layout = QHBoxLayout()
        button_layout.addWidget(process_btn)
        button_layout.addWidget(export_btn)
        button_layout.addWidget(simple_export_btn)
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
        # Settings menu
        settings_menu = self.menubar.addMenu("设置")

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

    def _handle_table_upload(self, file_path: Path, category: str):
        """处理表格文件验证和存储"""
        status_label = None
        try:
            if self._is_processing():
                QMessageBox.warning(self, '请稍候', '正在处理文件，请完成后再更换表格')
                return
            if file_path.suffix.lower() not in ALLOWED_TABLE_EXTENSIONS:
                QMessageBox.warning(self, "错误", "不支持的表格文件类型，请上传Excel或CSV文件")
                return

            # 更新状态为处理中
            if category in TEMPLATE_LABELS:
                status_label = self.template_rows[category][1]
                if file_path.suffix.lower() != '.xlsx':
                    raise ValueError('输出模板需为 .xlsx 文件')
                workbook = openpyxl.load_workbook(file_path, read_only=True)
                try:
                    simple_report = is_simple_report(workbook)
                    if category == 'simple_output_table' and not simple_report:
                        raise ValueError('请在简表模板栏上传 T-CD 数据简表')
                    if category == 'output_table' and (simple_report or '调价前' not in workbook.sheetnames):
                        raise ValueError('请在日报模板栏上传含“调价前”的日报；T-CD 简表请上传到简表模板栏')
                finally:
                    workbook.close()
            else:
                row_tuple = self.required_table_rows.get(
                    category) or self.optional_table_rows.get(category)
                _, status_label = row_tuple if row_tuple else (None, None)

            if status_label:
                status_label.setText("处理中...")
            QApplication.processEvents()  # 确保UI更新

            # 根据类别决定文件名和目标路径
            if category in TEMPLATE_LABELS:
                # Different slots may legitimately use the same filename.
                folder = self.output_dir / category
                folder.mkdir(parents=True, exist_ok=True)
                dest_path = folder / file_path.name
            else:
                # 其他表格添加时间戳
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                new_filename = f"{category}_{timestamp}{file_path.suffix}"
                dest_path = self.table_dir / new_filename

            # Copy file to destination directory
            if file_path.resolve() != dest_path.resolve():
                shutil.copy2(file_path, dest_path)
            for old_file in self.uploaded_files.get(category, []):
                if old_file != dest_path and old_file.exists():
                    old_file.unlink()
            if category == 'output_table':
                self.output_table_path = dest_path
            elif category == 'simple_output_table':
                self.simple_output_table_path = dest_path
            self._refresh_template_options()

            # Update tracking for all categories (including output_table)
            self.uploaded_files[category] = [dest_path]
            self.processing_status[category] = "已上传"
            self.processing_results[category] = {}  # Initialize empty results

            # 更新状态标签
            if status_label:
                status_label.setText(f"已上传：{file_path.name}")

            self._update_table(category)

        except Exception as e:
            logger.error(f"处理表格文件错误: {str(e)}")
            if status_label:
                status_label.setText("处理失败")
            QMessageBox.critical(self, "错误", f"表格文件处理失败: {str(e)}")

    def _handle_row_drop(self, event: QDropEvent, category: str):
        """处理整行拖放事件"""
        try:
            urls = event.mimeData().urls()
            if urls:
                file_path = Path(self._normalize_path(urls[0].toLocalFile()))
                # 根据类别和文件类型分别处理
                if category in TEMPLATE_LABELS or category in REQUIRED_TABLE_CATEGORIES + OPTIONAL_TABLE_CATEGORIES:
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
                    self._handle_image_upload(category, file_path)
                event.accept()
        except Exception as e:
            logger.error(f"拖放错误: {str(e)}")
            QMessageBox.critical(self, "错误", f"处理拖放失败: {str(e)}")
            event.ignore()

    def _handle_image_upload(self, category: str, file_path: Path):
        """Handle image files dropped onto the widget"""
        try:
            if self._is_processing():
                QMessageBox.warning(self, '请稍候', '正在处理文件，请完成后再上传')
                return
            if category not in REQUIRED_IMAGE_CATEGORIES + OPTIONAL_IMAGE_CATEGORIES:
                QMessageBox.warning(self, '错误', '请在模板或源表栏上传表格文件')
                return
            if file_path.suffix.lower() not in ALLOWED_IMAGE_EXTENSIONS:
                QMessageBox.warning(self, "错误", "不支持的图片文件类型，请上传JPG、PNG或BMP文件")
                return

            # Generate unique filename and save - preserve original extension
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            original_extension = file_path.suffix.lower()  # 保持原始扩展名
            new_filename = f"{category}_{timestamp}{original_extension}"
            dest_path = self.image_dir / new_filename

            # Copy file to destination
            shutil.copy2(file_path, dest_path)

            # Append to tracking list
            if category not in self.uploaded_files:
                self.uploaded_files[category] = []
            self.uploaded_files[category].append(dest_path)
            self.processing_status[category] = "已上传"

            # 获取对应的状态标签
            row_tuple = self.required_rows.get(
                category) or self.optional_rows.get(category)
            _, status_label = row_tuple if row_tuple else (None, None)
            count = len(self.uploaded_files[category])
            if status_label:
                status_label.setText(f"已上传 ({count}张)" if count > 1 else "已上传")

            self._update_table(category)

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
                self._handle_image_upload(category, Path(file_path))

        except Exception as e:
            logger.error(f"上传文件错误: {str(e)}")
            QMessageBox.critical(self, "错误", f"上传失败: {str(e)}")

    def _is_processing(self) -> bool:
        return self.files_to_process > 0 or bool(self.update_workers) or any(
            self.processing_status.get(category) == '更新中' for category in TEMPLATE_LABELS)

    def _refresh_template_options(self) -> None:
        self.simple_report = self.simple_output_table_path is not None
        self.simple_options.setVisible(self.simple_report)
        self.simple_hint.setVisible(self.simple_report)
        self.required_table_group.setTitle(
            '源表（仅填简表时，油品优惠表可选）' if self.simple_report
            else '必填表格（必须全部上传）')

    def _process_all_files(self) -> None:
        """Generate each uploaded template using its own update batch and save path."""
        if self._is_processing():
            return
        if not self._validate_required_files():
            QMessageBox.warning(self, '警告', '请先上传模板及对应的必需源表')
            return
        try:
            processor = None
            if self.simple_output_table_path:
                processor = SimpleReportProcessor(
                    replace(self.shift_config), self.simple_divisor.value(), self.simple_count_divisor.value(),
                    closing_balance=self.simple_closing_balance.text())
            self.pending_updates = []
            self.simple_pending_updates = []
            self.failed_outputs.clear()
            self._category_pending_count = {}
            self._category_partial_results = {}
            legacy_files = {category: files for category, files in self.uploaded_files.items()
                            if self.output_table_path and files and category not in TEMPLATE_LABELS}
            self.files_to_process = int(processor is not None) + sum(
                1 if category in REQUIRED_TABLE_CATEGORIES + OPTIONAL_TABLE_CATEGORIES else len(files)
                for category, files in legacy_files.items())
            for category, path in [('output_table', self.output_table_path),
                                   ('simple_output_table', self.simple_output_table_path)]:
                if path:
                    self.processing_status[category] = '处理中'
                    self._update_table(category)
            if processor is not None:
                worker = SimpleReportWorker(processor, {
                    category: self.uploaded_files[category][0] for category in SIMPLE_CATEGORIES
                    if self.uploaded_files.get(category)})
                worker.finished.connect(self._handle_table_processing_complete)
                worker.error.connect(self._handle_processing_error)
                self.active_workers.append(worker)
                worker.start()
            for category, files in legacy_files.items():
                if category in REQUIRED_TABLE_CATEGORIES + OPTIONAL_TABLE_CATEGORIES:
                    self._process_single_table(category, files[0])
                elif category in REQUIRED_IMAGE_CATEGORIES + OPTIONAL_IMAGE_CATEGORIES:
                    self._category_pending_count[category] = len(files)
                    self._category_partial_results[category] = []
                    for path in files:
                        self._process_single_image(category, path)
        except Exception as error:
            logger.error(f'Error in process_all_files: {error}')
            QMessageBox.critical(self, '错误', f'处理文件时出错: {error}')

    def _check_all_processing_complete(self) -> None:
        """Check if all files have been processed"""
        self.files_to_process -= 1

        # Only emit completion signal when all processing is done
        if self.files_to_process <= 0:
            self.files_to_process = 0
            self._apply_all_updates()

            # Schedule worker cleanup for next event loop iteration
            QTimer.singleShot(0, self._cleanup_workers)

    def _cleanup_workers(self) -> None:
        """Clean up finished workers in a separate event loop iteration"""
        active_workers = []
        for worker in self.active_workers:
            if worker.isFinished():
                worker.deleteLater()
            else:
                active_workers.append(worker)
        self.active_workers = active_workers

    def _process_single_image(self, category: str, file_path: Path) -> None:
        """Process a single image file"""
        try:
            # Update status
            self.processing_status[category] = "处理中"
            self._update_table(category)

            processor = InvoiceProcessor(self.shift_config)
            worker = ProcessingWorker(processor, file_path, category)

            # Connect signals
            worker.finished.connect(
                lambda result, cat=category: self._handle_processing_complete(
                    result, cat)
            )
            worker.error.connect(
                lambda error, cat=category: self._handle_processing_error(
                    error, cat)
            )

            self.active_workers.append(worker)

            # Start worker
            worker.start()
            logger.info(f"Started processing worker for {category}")

        except Exception as e:
            logger.error(f"Error processing image {category}: {str(e)}")
            self._handle_processing_error(str(e), category)
            # Ensure status is updated even if error occurs
            self._update_table(category)

    def _process_single_table(self, category: str, file_path: Path) -> None:
        """处理单个表格文件"""
        try:
            # 更新状态
            self.processing_status[category] = "处理中"
            self._update_table(category)

            # 为每个worker创建新的TableProcessor实例
            table_processor = TableProcessor(self.shift_config)

            # 创建工作线程
            worker = TableProcessingWorker(
                table_processor,
                file_path,
                category
            )

            worker.finished.connect(
                lambda result, cat=category: self._handle_table_processing_complete(
                    result, cat)
            )
            worker.error.connect(
                lambda error, cat=category: self._handle_processing_error(
                    error, cat)
            )

            self.active_workers.append(worker)

            # Start worker
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

            if category == 'simple_output_table' and not self.output_table_path:
                for source_category in SIMPLE_CATEGORIES:
                    if self.uploaded_files.get(source_category):
                        self.processing_status[source_category] = '完成'
                        self._update_table(source_category)

            if 'updates' in result:
                target = self.simple_pending_updates if category == 'simple_output_table' else self.pending_updates
                target.extend(result['updates'])

            self.processing_status[category] = '待写入' if category in TEMPLATE_LABELS else '完成'
            self._update_table(category)

            # Use QTimer to check completion status in next event loop
            QTimer.singleShot(0, self._check_all_processing_complete)

        except Exception as e:
            logger.error(f"Error in table processing completion: {str(e)}")
            self._handle_processing_error(str(e), category)

    def _handle_processing_complete(self, result: Dict, category: str) -> None:
        """Handle successful processing completion"""
        try:
            # Always add updates directly — ExcelUpdater handles accumulation
            if 'updates' in result:
                self.pending_updates.extend(result['updates'])

            if category in self._category_pending_count:
                # Multi-image: accumulate processed_data for display
                self._category_partial_results[category].append(result)
                self._category_pending_count[category] -= 1

                if self._category_pending_count[category] <= 0:
                    # All images done — merge processed_data for display only
                    merged_data: Dict[str, float] = {}
                    for r in self._category_partial_results[category]:
                        for key, value in r.get('processed_data', {}).items():
                            merged_data[key] = round(merged_data.get(key, 0) + value, 2)
                    self.processing_results[category] = merged_data
                    self.processing_status[category] = "完成"
                    self._update_table(category)
                else:
                    remaining = self._category_pending_count[category]
                    self.processing_status[category] = f"处理中 ({remaining}张剩余)"
                    self._update_table(category)
            else:
                # Single-file category
                self.processing_results[category] = result.get(
                    'processed_data', {})
                self.processing_status[category] = "完成"
                self._update_table(category)

            # Use QTimer to check completion status in next event loop
            QTimer.singleShot(0, self._check_all_processing_complete)

        except Exception as e:
            logger.error(f"Error in processing completion: {str(e)}")
            self._handle_processing_error(str(e), category)

    def _handle_processing_error(self, error_message: str, category: str) -> None:
        """Handle processing error"""
        self.failed_outputs.add('simple_output_table' if category == 'simple_output_table' else 'output_table')
        # Decrement pending count for multi-image categories
        if category in self._category_pending_count:
            self._category_pending_count[category] -= 1

        self.processing_status[category] = f"错误: {error_message}"
        self._update_table(category)

        # Use QTimer for error case as well
        QTimer.singleShot(0, self._check_all_processing_complete)

    def _on_all_processing_complete(self) -> None:
        if self.files_to_process <= 0 and not self.update_workers:
            self._apply_all_updates()

    def _apply_all_updates(self) -> None:
        """Never mix legacy and simple-report cell updates in the same workbook."""
        for category, path, updates in [
            ('output_table', self.output_table_path, self.pending_updates),
            ('simple_output_table', self.simple_output_table_path, self.simple_pending_updates),
        ]:
            if not path or category in self.update_workers:
                continue
            if category in self.failed_outputs:
                updates.clear()
                self.processing_status[category] = '处理失败，未写入'
                self._update_table(category)
                continue
            if not updates:
                continue
            try:
                self.processing_status[category] = '更新中'
                self._update_table(category)
                worker = ExcelUpdateWorker(path, list(updates))
                worker.finished.connect(
                    lambda success, message, c=category: self._handle_update_complete(success, message, c))
                self.update_workers[category] = worker
                worker.start()
            except Exception as error:
                self.update_workers.pop(category, None)
                self.processing_status[category] = '更新失败'
                self._update_table(category)
                QMessageBox.critical(self, '错误', f'{TEMPLATE_LABELS[category]}更新失败: {error}')

    def _handle_update_complete(self, success: bool, error_message: str, category: str) -> None:
        try:
            if success:
                self.processing_status[category] = ('已填写，待核对保留项'
                                                     if category == 'simple_output_table' else '完成')
                updates = self.simple_pending_updates if category == 'simple_output_table' else self.pending_updates
                updates.clear()
            else:
                self.processing_status[category] = '更新失败'
                QMessageBox.critical(self, '错误', f'{TEMPLATE_LABELS[category]}保存失败: {error_message}')
        finally:
            self._update_table(category)
            worker = self.update_workers.pop(category, None)
            if worker is not None:
                worker.wait()
                worker.deleteLater()

    def _update_table_row(self, category: str, row: int) -> None:
        """Update a specific row in the results table
        Args:
            category: The category of the file
            row: The row number to update
        """
        file_list = self.uploaded_files.get(category)
        if not file_list:
            return
        file_path = file_list[-1]  # Show the last uploaded file

        # Category
        category_item = QTableWidgetItem(TEMPLATE_LABELS.get(category, category))
        category_item.setData(Qt.ItemDataRole.UserRole, category)
        self.result_table.setItem(row, 0, category_item)

        # Filename - make it clickable
        if len(file_list) > 1:
            filename_item = QTableWidgetItem(f"{file_path.name} ({len(file_list)}张)")
        else:
            filename_item = QTableWidgetItem(file_path.name)
        filename_item.setData(Qt.ItemDataRole.UserRole, str(file_path))
        filename_item.setForeground(
            QColor(0, 0, 255))  # Make it look clickable
        filename_item.setToolTip("点击预览图片")
        self.result_table.setItem(row, 1, filename_item)

        # Status
        status_item = QTableWidgetItem(
            self.processing_status.get(category, "未处理"))
        # 根据不同状态设置不同的背景色
        if "错误" in status_item.text() or "失败" in status_item.text():
            status_item.setBackground(QColor(255, 200, 200))  # 浅红色
        elif status_item.text() == "完成":
            status_item.setBackground(QColor(200, 255, 200))  # 浅绿色
        elif status_item.text() == "处理中":
            status_item.setBackground(QColor(200, 200, 255))  # 浅蓝色
        elif status_item.text() == "已上传":
            status_item.setBackground(QColor(220, 220, 220))  # 灰色
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
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)  # Align text to top-left
        self.result_table.setItem(row, 3, result_item)

        # Action button
        if category in (REQUIRED_IMAGE_CATEGORIES + OPTIONAL_IMAGE_CATEGORIES):
            action_btn = QPushButton("重新上传")
            action_btn.clicked.connect(
                lambda checked, c=category: self._upload_file(c))
            self.result_table.setCellWidget(row, 4, action_btn)
        elif category in (REQUIRED_TABLE_CATEGORIES + OPTIONAL_TABLE_CATEGORIES + list(TEMPLATE_LABELS)):
            action_btn = QPushButton("重新上传")
            action_btn.clicked.connect(
                lambda checked, c=category: self._upload_table_file(c))
            self.result_table.setCellWidget(row, 4, action_btn)

        # Adjust row height to show all content
        self.result_table.resizeRowToContents(row)

    def _update_table(self, category: str | None = None) -> None:
        """Update the results table
        Args:
            category: Optional category to update. If None, update all rows
        """
        if category:
            # Find the row for this category
            row = -1
            for i in range(self.result_table.rowCount()):
                item = self.result_table.item(i, 0)
                if item is not None and item.data(Qt.ItemDataRole.UserRole) == category:
                    row = i
                    break

            # If row not found, we need to add a new row
            if row == -1:
                row = self.result_table.rowCount()
                self.result_table.insertRow(row)

            self._update_table_row(category, row)
        else:
            # Update all rows
            # First, clear the table
            self.result_table.setRowCount(0)

            # Then add a row for each uploaded file
            for category, _ in self.uploaded_files.items():
                row = self.result_table.rowCount()
                self.result_table.insertRow(row)
                self._update_table_row(category, row)

    def _handle_table_cell_click(self, row: int, column: int) -> None:
        """Handle table cell click to show preview"""
        if column == 1:  # Filename column
            item = self.result_table.item(row, column)
            if item:
                file_path = Path(item.data(Qt.ItemDataRole.UserRole))

                # 获取文件类型（从第一列）
                category_item = self.result_table.item(row, 0)
                if not category_item:
                    return

                category = category_item.data(Qt.ItemDataRole.UserRole)

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
                    if category in TEMPLATE_LABELS or category in REQUIRED_TABLE_CATEGORIES + OPTIONAL_TABLE_CATEGORIES:
                        # 表格预览
                        if file_path.suffix.lower() in ALLOWED_TABLE_EXTENSIONS:
                            self.preview_dialog = TablePreviewDialog(
                                file_path, self)
                            self.preview_dialog.show()
                        else:
                            QMessageBox.warning(self, "错误", "不支持的表格文件类型")
                    elif category in REQUIRED_IMAGE_CATEGORIES + OPTIONAL_IMAGE_CATEGORIES:
                        # 图片预览 — pass all images for this category
                        image_list = self.uploaded_files.get(category, [])
                        if image_list:
                            self.preview_dialog = ImagePreviewDialog(
                                image_list, self)
                            self.preview_dialog.show()
                except Exception as e:
                    print(f"Error accessing file: {str(e)}")
                    QMessageBox.critical(self, "错误", f"无法访问文件: {str(e)}")

    def _validate_required_files(self) -> bool:
        if not self.output_table_path and not self.simple_output_table_path:
            QMessageBox.warning(self, '警告', '请先上传日报模板或简表模板')
            return False
        required = REQUIRED_TABLE_CATEGORIES if self.output_table_path else SIMPLE_REQUIRED_CATEGORIES
        return all(self.uploaded_files.get(category) for category in required)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        """Handle widget events for clipboard paste support"""
        rows = {**self.template_rows, **self.required_rows, **self.optional_rows,
                **self.required_table_rows, **self.optional_table_rows}
        category = next((key for key, (widget, _) in rows.items() if obj == widget), None)

        if category:
            if event.type() == QEvent.Type.Enter:
                self.current_hover_category = category
                widget: QWidget = obj  # type: ignore[assignment]
                widget.setProperty("hovered", True)
                widget.style().unpolish(widget)
                widget.style().polish(widget)

                # Get the appropriate status label
                status_label = None
                if category in TEMPLATE_LABELS:
                    status_label = self.template_rows[category][1]
                else:
                    row_tuple = (self.required_rows.get(category) or
                                self.optional_rows.get(category) or
                                self.required_table_rows.get(category) or
                                self.optional_table_rows.get(category))
                    _, status_label = row_tuple if row_tuple else (None, None)

                if not status_label:
                    return True

                # 检查是否已上传文件
                if category in self.uploaded_files and len(self.uploaded_files[category]) > 0:
                    count = len(self.uploaded_files[category])
                    is_image_cat = category in REQUIRED_IMAGE_CATEGORIES + OPTIONAL_IMAGE_CATEGORIES
                    if is_image_cat and count > 1:
                        status_label.setText(f"已上传 ({count}张)")
                    else:
                        status_label.setText("已上传")
                    return True

                # 获取剪贴板数据
                mime_data = self.clipboard.mimeData()

                # 检查是否为表格类别
                is_table_category = (category in TEMPLATE_LABELS or
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

            elif event.type() == QEvent.Type.Leave:
                self.current_hover_category = None
                widget: QWidget = obj  # type: ignore[assignment]
                widget.setProperty("hovered", False)
                widget.style().unpolish(widget)
                widget.style().polish(widget)

                # Get the appropriate status label
                status_label = None
                if category in TEMPLATE_LABELS:
                    status_label = self.template_rows[category][1]
                else:
                    row_tuple = (self.required_rows.get(category) or
                                self.optional_rows.get(category) or
                                self.required_table_rows.get(category) or
                                self.optional_table_rows.get(category))
                    _, status_label = row_tuple if row_tuple else (None, None)

                if status_label:
                    # Check if file is already uploaded for this category
                    if category in self.uploaded_files and len(self.uploaded_files[category]) > 0:
                        count = len(self.uploaded_files[category])
                        is_image_cat = category in REQUIRED_IMAGE_CATEGORIES + OPTIONAL_IMAGE_CATEGORIES
                        if is_image_cat and count > 1:
                            status_label.setText(f"已上传 ({count}张)")
                        else:
                            status_label.setText("已上传")
                    else:
                        # 根据类别显示相应的默认提示文本
                        if category in TEMPLATE_LABELS or category in REQUIRED_TABLE_CATEGORIES + OPTIONAL_TABLE_CATEGORIES:
                            status_label.setText("拖放表格、点击上传或按Ctrl+V粘贴")
                        else:
                            status_label.setText("拖放图片、点击上传或按Ctrl+V粘贴")
                return True

            elif event.type() == QEvent.Type.KeyPress:
                key_event: QKeyEvent = event  # type: ignore[assignment]
                if (key_event.key() == Qt.Key.Key_V and
                    key_event.modifiers() == Qt.KeyboardModifier.ControlModifier and
                        self.current_hover_category == category):  # Only paste if mouse is hovering
                    # Check if it's a table category
                    self._handle_clipboard_paste(category)
                    return True

        return super().eventFilter(obj, event)

    def _handle_clipboard_paste(self, category: str) -> None:
        """Handle clipboard paste event for images"""
        if self._is_processing():
            QMessageBox.warning(self, '请稍候', '正在处理文件，请完成后再粘贴')
            return
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
                        self._handle_image_upload(category, file_path)
                        return
                    elif file_path.suffix.lower() in ALLOWED_TABLE_EXTENSIONS:
                        self._handle_table_upload(file_path, category)
                        return
                    else:
                        QMessageBox.warning(self, "错误", "不支持的文件类型")
                        if status_label:
                            status_label.setText("不支持的文件类型")
                        return
            elif mime_data.hasText():
                text = mime_data.text().strip()
                if Path(self._normalize_path(text)).exists():
                    file_path = Path(self._normalize_path(text))
                    if file_path.suffix.lower() in ALLOWED_IMAGE_EXTENSIONS:
                        self._handle_image_upload(category, file_path)
                        return
                    elif file_path.suffix.lower() in ALLOWED_TABLE_EXTENSIONS:
                        self._handle_table_upload(file_path, category)
                        return
                    else:
                        QMessageBox.warning(self, "错误", "不支持的图片文件类型")
                        if status_label:
                            status_label.setText("不支持的文件类型")
                        return
            elif mime_data.hasImage():
                if category not in REQUIRED_IMAGE_CATEGORIES + OPTIONAL_IMAGE_CATEGORIES:
                    QMessageBox.warning(self, '错误', '请在模板或源表栏粘贴表格文件')
                    return
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
                            qba = mime_data.data('x-qt-image')
                            format_data = bytes(qba.data())  # type: ignore[arg-type]
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
                              temp_path: Path, status_label: QLabel | None) -> None:
        """Handle image save completion"""
        if success:
            # Append to tracking list
            if category not in self.uploaded_files:
                self.uploaded_files[category] = []
            self.uploaded_files[category].append(temp_path)
            self.processing_status[category] = "已上传"
            count = len(self.uploaded_files[category])
            if status_label:
                status_label.setText(f"已上传 ({count}张)" if count > 1 else "已上传")
            self._update_table(category)
        else:
            QMessageBox.critical(self, "错误", f"保存图片失败: {error_msg}")
            if status_label:
                status_label.setText("保存失败")

        # 清理工作线程
        if hasattr(self, 'save_worker'):
            self.save_worker.quit()
            self.save_worker.wait()
            self.save_worker.deleteLater()

    def _clear_category(self, category: str) -> None:
        """Clear one source or template slot without affecting the other output."""
        if self._is_processing():
            QMessageBox.warning(self, '提示', '正在处理文件，请完成后再清除')
            return
        if category in self.uploaded_files:
            for file_path in self.uploaded_files[category]:
                try:
                    if file_path.exists():
                        file_path.unlink()
                except Exception as e:
                    logger.error(f"删除文件失败: {str(e)}")
            self.uploaded_files[category] = []

        self.processing_status.pop(category, None)
        self.processing_results.pop(category, None)

        if category == 'output_table':
            self.output_table_path = None
        elif category == 'simple_output_table':
            self.simple_output_table_path = None
            self.simple_closing_balance.clear()
        self._refresh_template_options()

        # Reset status label
        _, status_label = (self.template_rows.get(category) or self.required_rows.get(category) or
                           self.optional_rows.get(category) or
                           (None, None))
        if status_label:
            status_label.setText('拖放模板、点击上传或按 Ctrl+V 粘贴' if category in TEMPLATE_LABELS
                                 else '拖放图片、点击上传或按Ctrl+V粘贴')

        # Remove from results table
        for i in range(self.result_table.rowCount()):
            item = self.result_table.item(i, 0)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == category:
                self.result_table.removeRow(i)
                break

    def _upload_table_file(self, category: str) -> None:
        """Handle table file upload for a specific category."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, f"选择{TEMPLATE_LABELS.get(category, category)}文件", "",
            "Table Files (*.xlsx *.xls *.csv)"
        )
        if file_path:
            self._handle_table_upload(Path(file_path), category)

    def _on_date_changed(self, new_date: QDate) -> None:
        """Handle date selection change"""
        self.shift_config.date = new_date.toPython()  # type: ignore[assignment]

    def _on_shift_time_changed(self, new_datetime: QDateTime) -> None:
        """Handle shift time selection change"""
        self.shift_config.shift_time = new_datetime.toPython()  # type: ignore[assignment]

    def _on_work_start_time_changed(self, new_datetime: QDateTime) -> None:
        """Handle work start time selection change"""
        self.shift_config.work_start_time = new_datetime.toPython()  # type: ignore[assignment]

    def _on_gas_price_changed(self, new_price: float) -> None:
        """Handle gas price change"""
        if new_price <= 0:
            QMessageBox.warning(self, "警告", "汽油价格必须大于0")
            self.gas_price_input.setValue(
                self.shift_config.gas_price)  # Revert to previous value
            return
        self.shift_config.gas_price = new_price

    def _perform_reset(self) -> None:
        """Perform the actual reset operations without confirmation dialog"""
        try:
            # Delete uploaded files
            for file_list in self.uploaded_files.values():
                for file_path in file_list:
                    try:
                        if file_path.exists():
                            file_path.unlink()
                    except Exception as e:
                        logger.error(f"Error deleting file {file_path}: {str(e)}")

            # Clean up table directory
            for file_path in self.table_dir.glob('*'):
                try:
                    if file_path.is_file():
                        file_path.unlink()
                except Exception as e:
                    logger.error(
                        f"Error deleting table file {file_path}: {str(e)}")

            # Clean up output directory
            for file_path in self.output_dir.glob('*'):
                try:
                    if file_path.is_file():
                        file_path.unlink()
                except Exception as e:
                    logger.error(
                        f"Error deleting output file {file_path}: {str(e)}")

            # Clear tracking dictionaries
            self.uploaded_files.clear()
            self.processing_status.clear()
            self.processing_results.clear()
            self.pending_updates.clear()
            self._category_pending_count.clear()
            self._category_partial_results.clear()
            self.output_table_path = None
            self.simple_output_table_path = None
            self.simple_pending_updates.clear()
            self.failed_outputs.clear()
            self.simple_report = False
            self.simple_options.hide()
            self.simple_hint.hide()
            self.simple_closing_balance.clear()
            self.required_table_group.setTitle('必填表格（必须全部上传）')

            # Reset status labels
            for _, status_label in self.required_rows.values():
                status_label.setText("拖放图片、点击上传或按Ctrl+V粘贴")
            for _, status_label in self.optional_rows.values():
                status_label.setText("拖放图片、点击上传或按Ctrl+V粘贴")
            for _, status_label in self.required_table_rows.values():
                status_label.setText("拖放表格、点击上传或按Ctrl+V粘贴")
            for _, status_label in self.optional_table_rows.values():
                status_label.setText("拖放表格、点击上传或按Ctrl+V粘贴")
            for _, label in self.template_rows.values():
                label.setText('拖放模板、点击上传或按 Ctrl+V 粘贴')

            # Clear result table
            self.result_table.setRowCount(0)

            logger.info("Successfully reset all content")

        except Exception as e:
            logger.error(f"Error during reset: {str(e)}")
            QMessageBox.critical(self, "错误", f"重置过程中出错: {str(e)}")

    def closeEvent(self, event) -> None:
        if self._is_processing():
            QMessageBox.warning(self, '提示', '正在处理文件，请完成后再关闭')
            event.ignore()
            return
        self._perform_reset()
        event.accept()

    def _reset_all(self) -> None:
        """Reset all uploaded files and UI state"""
        if self._is_processing():
            QMessageBox.warning(self, '提示', '正在处理文件，请完成后再重置')
            return
        # Show confirmation dialog
        reply = QMessageBox.question(
            self,
            "确认重置",
            "确定要重置所有内容吗？这将清除所有已上传的文件。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.No:
            return

        self._perform_reset()
        QMessageBox.information(self, "成功", "已重置所有内容", QMessageBox.StandardButton.Ok)

    def _export_output_table(self, category: str = 'output_table') -> None:
        """Export the output table to a user-specified location"""
        if self._is_processing():
            QMessageBox.warning(self, "提示", "表格正在处理，请完成后再输出")
            return
        path = self.simple_output_table_path if category == 'simple_output_table' else self.output_table_path
        if not path or not path.exists():
            QMessageBox.warning(self, "警告", f"没有可导出的{TEMPLATE_LABELS[category]}")
            return

        try:
            # Get the destination path from user
            dest_path, _ = QFileDialog.getSaveFileName(
                self,
                '导出简表' if category == 'simple_output_table' else '导出日报',
                str(path.name),
                "Excel Files (*.xlsx *.xls);;All Files (*.*)"
            )

            if dest_path:
                # Copy the file
                shutil.copy2(path, dest_path)
                QMessageBox.information(self, "成功", "表格导出成功", QMessageBox.StandardButton.Ok)
        except Exception as e:
            logger.error(f"导出表格错误: {str(e)}")
            QMessageBox.critical(self, "错误", f"导出表格失败: {str(e)}")

    def _get_datetime_format(self) -> str:
        """Get the appropriate datetime format based on system"""
        if platform.system().lower() == 'windows':
            return "yyyy年MM月dd日 HH:mm:ss"
        else:
            # macOS/Linux可能需要不同的格式
            return "yyyy-MM-dd HH:mm:ss"

    def _get_date_format(self) -> str:
        """Get the appropriate date format based on system"""
        if platform.system().lower() == 'windows':
            return "yyyy年MM月dd日"
        else:
            # macOS/Linux可能需要不同的格式
            return "yyyy-MM-dd"

    def _create_separator(self) -> QFrame:
        """Create a standard separator line"""
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Plain)  # 改为Plain而不是Sunken
        line.setStyleSheet("QFrame { background-color: #cccccc; border: none; }")
        line.setFixedHeight(2)  # 使用setFixedHeight替代setMaximumHeight
        return line
