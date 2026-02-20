from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                               QPushButton, QMessageBox, QApplication,
                               QSizePolicy, QTableWidget, QTableWidgetItem)
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QImage
from pathlib import Path
from typing import List
import pandas as pd


class ImagePreviewDialog(QDialog):
    """Dialog for displaying image preview with left/right navigation for multiple images"""

    def __init__(self, image_paths: List[Path], parent=None, start_index: int = 0):
        super().__init__(parent)
        self.setWindowTitle("图片预览")
        self.setModal(True)
        self.setMinimumSize(800, 600)

        self.image_paths = image_paths
        self.current_index = start_index
        self.original_pixmap: QPixmap | None = None

        # Create main layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Create image label
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self.image_label)

        # Navigation bar (only shown when multiple images)
        if len(self.image_paths) > 1:
            nav_layout = QHBoxLayout()
            nav_layout.setContentsMargins(10, 5, 10, 5)

            self.prev_btn = QPushButton("◀ 上一张")
            self.prev_btn.setFixedWidth(100)
            self.prev_btn.clicked.connect(self._show_prev)

            self.counter_label = QLabel()
            self.counter_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

            self.next_btn = QPushButton("下一张 ▶")
            self.next_btn.setFixedWidth(100)
            self.next_btn.clicked.connect(self._show_next)

            nav_layout.addWidget(self.prev_btn)
            nav_layout.addStretch()
            nav_layout.addWidget(self.counter_label)
            nav_layout.addStretch()
            nav_layout.addWidget(self.next_btn)
            layout.addLayout(nav_layout)

        # Load initial image
        self._load_current_image()

    def _load_current_image(self):
        """Load and display the image at current_index"""
        if not self.image_paths:
            return

        image_path = self.image_paths[self.current_index]
        try:
            pixmap = QPixmap(str(image_path))
            if pixmap.isNull():
                image = QImage(str(image_path))
                if image.isNull():
                    raise Exception("Failed to load image")
                if image.format() not in [QImage.Format.Format_RGB32, QImage.Format.Format_ARGB32]:
                    image = image.convertToFormat(QImage.Format.Format_RGB32)
                pixmap = QPixmap.fromImage(image)
                if pixmap.isNull():
                    raise Exception("Failed to convert image to pixmap")

            self.original_pixmap = pixmap

            # Resize window to fit image
            screen = QApplication.primaryScreen().geometry()
            max_width = int(screen.width() * 0.8)
            max_height = int(screen.height() * 0.8)

            if pixmap.width() > max_width or pixmap.height() > max_height:
                scaled = pixmap.scaled(
                    max_width, max_height,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation)
                self.image_label.setPixmap(scaled)
                self.resize(scaled.width(), scaled.height() + 40)
            else:
                self.image_label.setPixmap(pixmap)
                self.resize(pixmap.width(), pixmap.height() + 40)

        except Exception as e:
            self.image_label.setText(f"图片加载错误: {e}")

        # Update navigation
        if len(self.image_paths) > 1:
            self.counter_label.setText(
                f"{self.current_index + 1} / {len(self.image_paths)}  —  {image_path.name}")
            self.prev_btn.setEnabled(self.current_index > 0)
            self.next_btn.setEnabled(self.current_index < len(self.image_paths) - 1)

    def _show_prev(self):
        if self.current_index > 0:
            self.current_index -= 1
            self._load_current_image()

    def _show_next(self):
        if self.current_index < len(self.image_paths) - 1:
            self.current_index += 1
            self._load_current_image()

    def showEvent(self, event):
        super().showEvent(event)
        self.update_image_scale()

    def update_image_scale(self):
        if self.original_pixmap and not self.original_pixmap.isNull():
            available_size = self.image_label.size()
            scaled_pixmap = self.original_pixmap.scaled(
                max(10, available_size.width() - 20),
                max(10, available_size.height() - 20),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
            self.image_label.setPixmap(scaled_pixmap)


class TablePreviewDialog(QDialog):
    """Dialog for displaying table preview"""

    def __init__(self, file_path: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("表格预览")
        self.setModal(True)
        self.setMinimumSize(800, 600)

        # Create main layout
        layout = QVBoxLayout(self)

        # Create table widget
        self.table_widget = QTableWidget()
        self.table_widget.setAlternatingRowColors(True)

        # Add close button
        close_button = QPushButton("关闭")
        close_button.setFixedWidth(100)
        close_button.clicked.connect(self.close)

        # Add widgets to layout
        layout.addWidget(self.table_widget)
        layout.addWidget(close_button, alignment=Qt.AlignmentFlag.AlignCenter)

        # Load table data
        self.load_table_data(file_path)

    def load_table_data(self, file_path: Path):
        """Load table data from file"""
        try:
            # Read file based on extension
            if file_path.suffix.lower() == '.csv':
                df = pd.read_csv(file_path)
            else:  # Excel files
                df = pd.read_excel(file_path)

            # Disable updates during data loading to prevent flickering
            self.table_widget.setUpdatesEnabled(False)

            # Set table dimensions
            row_count = min(1000, len(df))
            self.table_widget.setRowCount(row_count)
            self.table_widget.setColumnCount(len(df.columns))

            # Set headers
            self.table_widget.setHorizontalHeaderLabels(list(df.columns))

            # Populate data
            for row in range(row_count):
                for col in range(len(df.columns)):
                    value = str(df.iloc[row, col])
                    item = QTableWidgetItem(value)
                    self.table_widget.setItem(row, col, item)

            # Optimize column widths
            self.table_widget.resizeColumnsToContents()

            # Re-enable updates
            self.table_widget.setUpdatesEnabled(True)

            if len(df) > 1000:
                QMessageBox.information(
                    self, "提示", "由于数据量较大，仅显示前1000行数据",
                    QMessageBox.StandardButton.Ok)

        except Exception as e:
            self.table_widget.setUpdatesEnabled(True)
            QMessageBox.critical(self, "错误", f"无法加载表格文件: {str(e)}")
            self.close()
