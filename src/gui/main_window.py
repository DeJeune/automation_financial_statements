from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                              QTableWidget, QTableWidgetItem, QPushButton,
                              QFileDialog, QGroupBox, QLabel, QMessageBox,
                              QHeaderView, QApplication, QScrollArea, QSplitter)
from PySide6.QtCore import Qt, QSize, Signal, QObject, QThread, QEvent
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent, QImage, QKeyEvent
from pathlib import Path
import asyncio
import shutil
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import json
import tempfile

from src.utils.invoice_processor import InvoiceProcessor
from src.utils.logger import logger

REQUIRED_CATEGORIES = [
    "油品统计表", "客户消费汇总", "抖音",
    "货车帮", "滴滴加油", "国通1", "国通2", "现金"
]
OPTIONAL_CATEGORIES = ["超市优惠券核销单", "团油"]
ALLOWED_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.tiff', '.bmp'}

class FileProcessingSignals(QObject):
    processing_complete = Signal(dict, str)

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
            result = loop.run_until_complete(
                self.processor.process_invoice(self.file_path)
            )
            self.finished.emit(result, self.category)
        except Exception as e:
            logger.error(f"Error processing {self.category}: {str(e)}")
            self.error.emit(str(e), self.category)
        finally:
            loop.close()

class InvoiceMainWindow(QMainWindow):
    """Main window for the invoice processing application"""

    def __init__(self):
        super().__init__()
        self.image_dir = Path("images")
        self.image_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir = Path("output/table")  # Add output directory
        self.output_dir.mkdir(parents=True, exist_ok=True)  # Create if not exists
        self.processor = InvoiceProcessor()
        
        # Track uploaded files and their status
        self.uploaded_files: Dict[str, Path] = {}
        self.processing_status: Dict[str, str] = {}
        self.processing_results: Dict[str, dict] = {}
        
        # Initialize tracking dictionaries
        self.required_rows = {}
        self.optional_rows = {}
        self.output_table_path = None
        
        self.init_ui()
        self.workers: List[ProcessingWorker] = []
        
        # Enable clipboard monitoring
        self.clipboard = QApplication.clipboard()
        self.current_hover_category = None

    def init_ui(self):
        """Initialize the user interface"""
        self.setWindowTitle("发票处理系统")
        self.setMinimumSize(QSize(1200, 800))
        
        # Create main splitter
        main_splitter = QSplitter(Qt.Vertical)
        
        # Create scroll area for upload section
        upload_scroll = QScrollArea()
        upload_scroll.setWidgetResizable(True)
        upload_widget = QWidget()
        upload_layout = QVBoxLayout(upload_widget)
        
        # Required files section
        required_group = QGroupBox("必选文件（必须全部上传）")
        required_layout = QVBoxLayout()
        
        for category in REQUIRED_CATEGORIES:
            # 创建整行widget作为拖放区域
            row_widget = QWidget()
            row_widget.setAcceptDrops(True)
            row_widget.setStyleSheet("""
                QWidget {
                    border: 2px dashed #aaa;
                    border-radius: 5px;
                    padding: 5px;
                    margin: 2px;
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
            category_label.setMinimumWidth(100)
            status_label = QLabel("拖放文件、点击上传或按Ctrl+V粘贴")
            upload_btn = QPushButton("上传")
            upload_btn.setMaximumWidth(60)
        
            # 连接信号
            upload_btn.clicked.connect(lambda checked, c=category: self._upload_file(c))
        
            # 设置拖放事件
            row_widget.dragEnterEvent = lambda e: e.acceptProposedAction() if e.mimeData().hasUrls() else None
            row_widget.dropEvent = lambda e, c=category: self._handle_row_drop(e, c)
        
            # 添加到布局
            row_layout.addWidget(category_label)
            row_layout.addWidget(status_label, stretch=1)  # 让状态标签占据剩余空间
            row_layout.addWidget(upload_btn)
        
            required_layout.addWidget(row_widget)
            self.required_rows[category] = (row_widget, status_label)

        required_group.setLayout(required_layout)
        upload_layout.addWidget(required_group)
        
        # Output table section
        output_group = QGroupBox("输出表格")
        output_layout = QVBoxLayout()
       # 创建表格上传行
        table_row = QWidget()
        table_row.setAcceptDrops(True)
        table_row.setStyleSheet("""
            QWidget {
                border: 2px dashed #aaa;
                border-radius: 5px;
                padding: 5px;
                margin: 2px;
            }
            QWidget:hover {
                background-color: #f0f0f0;
            }
        """)
        
        row_layout = QHBoxLayout(table_row)
        row_layout.setContentsMargins(10, 5, 10, 5)
        
        # 添加行内容并保存为实例变量
        self.table_status_label = QLabel("拖拽表格文件或点击上传")  # 修改这里，将其保存为实例变量
        upload_table_btn = QPushButton("上传")
        upload_table_btn.setMaximumWidth(60)
        
        # 连接信号
        upload_table_btn.clicked.connect(self._upload_table_file)
        
        # 设置拖放事件
        table_row.dragEnterEvent = lambda e: e.acceptProposedAction() if e.mimeData().hasUrls() else None
        table_row.dropEvent = self._handle_table_drop
        
        # 添加到布局
        row_layout.addWidget(self.table_status_label, stretch=1)
        row_layout.addWidget(upload_table_btn)
        
        output_layout.addWidget(table_row)
        output_group.setLayout(output_layout)
        upload_layout.addWidget(output_group)
        
        # Optional files section
        optional_group = QGroupBox("可选文件")
        optional_layout = QVBoxLayout()
        
        # 创建可选文件行
        for category in OPTIONAL_CATEGORIES:
            # 创建整行widget作为拖放区域
            row_widget = QWidget()
            row_widget.setAcceptDrops(True)
            row_widget.setStyleSheet("""
                QWidget {
                    border: 2px dashed #aaa;
                    border-radius: 5px;
                    padding: 5px;
                    margin: 2px;
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
            category_label.setMinimumWidth(100)
            status_label = QLabel("拖放文件、点击上传或按Ctrl+V粘贴")
            upload_btn = QPushButton("上传")
            upload_btn.setMaximumWidth(60)
            
            # 连接信号
            upload_btn.clicked.connect(lambda checked, c=category: self._upload_file(c, optional=True))
        
            # 设置拖放事件
            row_widget.dragEnterEvent = lambda e: e.acceptProposedAction() if e.mimeData().hasUrls() else None
            row_widget.dropEvent = lambda e, c=category: self._handle_row_drop(e, c)
        
            # 添加到布局
            row_layout.addWidget(category_label)
            row_layout.addWidget(status_label, stretch=1)
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
        
        # Add components to results layout
        results_layout.addWidget(self.result_table)
        results_layout.addWidget(process_btn)
        
        # Set results scroll content
        results_scroll.setWidget(results_widget)
        
        # Add scroll areas to splitter
        main_splitter.addWidget(upload_scroll)
        main_splitter.addWidget(results_scroll)
        
        # Set equal sizes
        main_splitter.setSizes([self.height() // 2, self.height() // 2])
        
        # Set central widget
        self.setCentralWidget(main_splitter)
    
    def _handle_table_drop(self, event: QDropEvent):
        """处理表格文件拖放事件"""
        urls = event.mimeData().urls()
        if urls:
            file_path = Path(urls[0].toLocalFile())
            self._handle_table_upload(file_path)
    
    def _upload_table_file(self):
        """处理表格文件上传"""
        try:
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                "选择输出表格文件",
                "",
                "表格文件 (*.xlsx *.xls *.csv)"
            )
            if file_path:
                self._handle_table_upload(Path(file_path))
        except Exception as e:
            logger.error(f"上传表格文件错误: {str(e)}")
            QMessageBox.critical(self, "错误", f"表格上传失败: {str(e)}")
    
    def _handle_table_upload(self, file_path: Path):
        """处理表格文件验证和存储"""
        if file_path.suffix.lower() not in {'.xlsx', '.xls', '.csv'}:
            QMessageBox.warning(self, "错误", "仅支持Excel和CSV文件")
            return
        
        try:
            # Generate unique filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            new_filename = f"output_table_{timestamp}{file_path.suffix}"
            dest_path = self.output_dir / new_filename
        
            # Copy file to output directory
            shutil.copy2(file_path, dest_path)
        
            self.output_table_path = dest_path
            self.table_status_label.setText(f"已上传: {file_path.name}")
            self.table_status_label.setStyleSheet("color: green;")
        except Exception as e:
            logger.error(f"复制表格文件错误: {str(e)}")
            QMessageBox.critical(self, "错误", f"表格文件处理失败: {str(e)}")

    def _handle_row_drop(self, event: QDropEvent, category: str):
        """处理整行拖放事件"""
        urls = event.mimeData().urls()
        if urls:
            file_path = Path(urls[0].toLocalFile())
            self._handle_file_drop(category, file_path)

    def _handle_file_drop(self, category: str, file_path: Path):
        """Handle files dropped onto the widget"""
        try:
            if file_path.suffix.lower() not in ALLOWED_EXTENSIONS:
                QMessageBox.warning(self, "错误", "不支持的文件类型")
                return

            # Generate unique filename and save
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            new_filename = f"{category}_{timestamp}{file_path.suffix}"
            dest_path = self.image_dir / new_filename
        
            # Copy file to destination
            shutil.copy2(file_path, dest_path)
        
            # Update tracking
            self.uploaded_files[category] = dest_path
            self.processing_status[category] = "已上传"
            
             # 获取对应的按钮
            _, status_label = self.required_rows[category]
            status_label.setText("已上传")
        
            self._update_table()
        
        except Exception as e:
            logger.error(f"拖放文件错误: {str(e)}")
            QMessageBox.critical(self, "错误", f"文件处理失败: {str(e)}")

    def _upload_file(self, category: str, optional: bool = False) -> None:
        """Handle file upload for a specific category"""
        try:
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                f"选择{category}图片",
                "",
                "Image Files (*.png *.jpg *.jpeg *.tiff *.bmp)"
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
        
        for category, file_path in self.uploaded_files.items():
            if self.processing_status[category] != "处理中":
                self._process_single_file(category, file_path)

    def _process_single_file(self, category: str, file_path: Path) -> None:
        """Process a single file"""
        try:
            # Update status
            self.processing_status[category] = "处理中"
            self._update_table()
            
            # Create and start worker
            worker = ProcessingWorker(self.processor, file_path, category)
            worker.finished.connect(self._handle_processing_complete)
            worker.error.connect(self._handle_processing_error)
            
            # Keep reference to prevent garbage collection
            self.workers.append(worker)
            worker.start()
            
        except Exception as e:
            logger.error(f"Error starting processing: {str(e)}")
            self._handle_processing_error(str(e), category)

    def _handle_processing_complete(self, result: Dict, category: str) -> None:
        """Handle successful processing completion"""
        self.processing_results[category] = result
        self.processing_status[category] = "完成"
        self._update_table()
        
        # Remove worker
        self.workers = [w for w in self.workers if w.category != category]

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
            
            # Filename
            self.result_table.setItem(row, 1, QTableWidgetItem(file_path.name))
            
            # Status
            status_item = QTableWidgetItem(self.processing_status.get(category, "未处理"))
            if "错误" in status_item.text():
                status_item.setBackground(QColor(255, 200, 200))
            elif status_item.text() == "完成":
                status_item.setBackground(QColor(200, 255, 200))
            self.result_table.setItem(row, 2, status_item)
            
            # Result
            result = self.processing_results.get(category, {})
            result_text = json.dumps(result, ensure_ascii=False, indent=2) if result else ""
            self.result_table.setItem(row, 3, QTableWidgetItem(result_text))
            
            # Action button
            if category in REQUIRED_CATEGORIES:
                action_btn = QPushButton("重新上传")
                action_btn.clicked.connect(lambda _, c=category: self._upload_file(c))
                self.result_table.setCellWidget(row, 4, action_btn)

    def _validate_required_files(self) -> bool:
        """验证所有必填文件和表格文件已上传"""
        has_required = all(category in self.uploaded_files for category in REQUIRED_CATEGORIES)
        has_table = self.output_table_path is not None
        if not has_table:
            QMessageBox.warning(self, "警告", "请先上传输出表格文件")
        return has_required and has_table

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        """Handle widget events for clipboard paste support"""
        # Check if the object is one of our upload widgets
        category = None
        for cat, (widget, _) in self.required_rows.items():
            if obj == widget:
                category = cat
                break
        if not category:
            for cat, (widget, _) in self.optional_rows.items():
                if obj == widget:
                    category = cat
                    break
        
        if category:
            if event.type() == QEvent.Enter:
                self.current_hover_category = category
                _, status_label = self.required_rows.get(category) or self.optional_rows.get(category)
                if self.clipboard.mimeData().hasImage():
                    status_label.setText("按Ctrl+V粘贴图片")
                return True
            
            elif event.type() == QEvent.Leave:
                self.current_hover_category = None
                _, status_label = self.required_rows.get(category) or self.optional_rows.get(category)
                # Check if file is already uploaded for this category
                if category in self.uploaded_files:
                    status_label.setText("已上传")
                else:
                    status_label.setText("拖放文件、点击上传或按Ctrl+V粘贴")
                return True
            
            elif event.type() == QEvent.KeyPress:
                key_event = QKeyEvent(event)
                if (key_event.key() == Qt.Key_V and 
                    key_event.modifiers() == Qt.ControlModifier and
                    self.current_hover_category == category):  # Only paste if mouse is hovering
                    self._handle_clipboard_paste(category)
                    return True
        
        return super().eventFilter(obj, event)

    def _handle_clipboard_paste(self, category: str) -> None:
        """Handle clipboard paste event for images"""
        try:
            mime_data = self.clipboard.mimeData()
            if mime_data.hasImage():
                image = QImage(mime_data.imageData())
                if not image.isNull():
                    # Save image to temp file
                    temp_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
                    temp_path = Path(temp_file.name)
                    image.save(str(temp_path))
                    
                    # Process the image file
                    self._handle_file_drop(category, temp_path)
                    
                    # Clean up temp file
                    temp_file.close()
                    temp_path.unlink()
                else:
                    QMessageBox.warning(self, "错误", "剪贴板中的图片无效")
            else:
                QMessageBox.warning(self, "错误", "剪贴板中没有图片")
        except Exception as e:
            logger.error(f"粘贴图片错误: {str(e)}")
            QMessageBox.critical(self, "错误", f"粘贴图片失败: {str(e)}")