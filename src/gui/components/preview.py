from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton, QMessageBox, QApplication, QSizePolicy, QTableWidget, QTableWidgetItem
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QImage
from pathlib import Path
import pandas as pd

class ImagePreviewDialog(QDialog):
    """Dialog for displaying image preview"""
    def __init__(self, image_path: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("图片预览")
        self.setModal(True)
        self.setMinimumSize(800, 600)
        
        print(f"\nImage Preview Dialog:")
        print(f"Loading image from: {image_path}")
        
        # Create main layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Create image label
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        # Load image
        try:
            # 先尝试直接加载
            self.original_pixmap = QPixmap(str(image_path))
            if self.original_pixmap.isNull():
                # 如果直接加载失败，尝试通过QImage加载并转换
                print("Direct pixmap loading failed, trying through QImage")
                image = QImage(str(image_path))
                if image.isNull():
                    raise Exception("Failed to load image")
                
                # 确保图片格式正确
                if image.format() not in [QImage.Format_RGB32, QImage.Format_ARGB32]:
                    print(f"Converting image format from {image.format()}")
                    image = image.convertToFormat(QImage.Format_RGB32)
                
                self.original_pixmap = QPixmap.fromImage(image)
                if self.original_pixmap.isNull():
                    raise Exception("Failed to convert image to pixmap")
            
            print(f"Image loaded successfully. Size: {self.original_pixmap.width()}x{self.original_pixmap.height()}")
            
            # 调整窗口大小以适应图片
            screen = QApplication.primaryScreen().geometry()
            img_width = self.original_pixmap.width()
            img_height = self.original_pixmap.height()
            
            # 如果图片尺寸超过屏幕80%，则按比例缩小
            max_width = int(screen.width() * 0.8)
            max_height = int(screen.height() * 0.8)
            
            if img_width > max_width or img_height > max_height:
                scaled_pixmap = self.original_pixmap.scaled(
                    max_width,
                    max_height,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )
                self.image_label.setPixmap(scaled_pixmap)
                # 设置窗口大小为缩放后的图片大小
                self.resize(scaled_pixmap.width(), scaled_pixmap.height())
            else:
                self.image_label.setPixmap(self.original_pixmap)
                # 设置窗口大小为原始图片大小
                self.resize(img_width, img_height)
            
        except Exception as e:
            error_msg = f"图片加载错误: {str(e)}"
            print(f"Error: {error_msg}")
            QMessageBox.critical(self, "错误", error_msg)
            self.close()
            return
            
        # Add image label to layout
        layout.addWidget(self.image_label)
        
        print("Dialog setup complete")

    def resizeEvent(self, event):
        """Handle window resize"""
        super().resizeEvent(event)
        # 窗口大小变化时不需要重新缩放图片
        pass

    def showEvent(self, event):
        """在对话框显示时更新图片缩放"""
        super().showEvent(event)
        self.update_image_scale()
        print("Dialog shown, initial scale applied")

    def update_image_scale(self):
        """Update the image scale to fit the window"""
        if hasattr(self, 'original_pixmap') and not self.original_pixmap.isNull():
            print(f"Scaling image. Original size: {self.original_pixmap.width()}x{self.original_pixmap.height()}")
            
            # 获取可用空间
            available_size = self.image_label.size()
            print(f"Label available size: {available_size.width()}x{available_size.height()}")
            
            # 计算缩放后的尺寸，保持一定边距
            scaled_pixmap = self.original_pixmap.scaled(
                max(10, available_size.width() - 20),
                max(10, available_size.height() - 20),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            print(f"Scaled size: {scaled_pixmap.width()}x{scaled_pixmap.height()}")
            
            # 设置图片并强制更新
            self.image_label.setPixmap(scaled_pixmap)
            print(f"Pixmap set to label. Label size after: {self.image_label.size()}")
            
            # 强制重绘
            self.image_label.repaint()

    def fit_to_window(self):
        """Scale image to fit the window"""
        print("Fitting image to window")
        self.update_image_scale()

    def show_original_size(self):
        """Show image in its original size"""
        if hasattr(self, 'original_pixmap') and not self.original_pixmap.isNull():
            print(f"Showing original size: {self.original_pixmap.width()}x{self.original_pixmap.height()}")
            self.image_label.setPixmap(self.original_pixmap)
            # 强制重绘
            self.image_label.repaint()

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
        layout.addWidget(close_button, alignment=Qt.AlignCenter)
        
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
            
            # Set table dimensions
            self.table_widget.setRowCount(min(1000, len(df)))  # 限制最多显示1000行
            self.table_widget.setColumnCount(len(df.columns))
            
            # Set headers
            self.table_widget.setHorizontalHeaderLabels(df.columns)
            
            # Populate data
            for row in range(min(1000, len(df))):
                for col in range(len(df.columns)):
                    value = str(df.iloc[row, col])
                    item = QTableWidgetItem(value)
                    self.table_widget.setItem(row, col, item)
            
            # Optimize column widths
            self.table_widget.resizeColumnsToContents()
            
            if len(df) > 1000:
                QMessageBox.information(self, "提示", "由于数据量较大，仅显示前1000行数据")
                
        except Exception as e:
            QMessageBox.critical(self, "错误", f"无法加载表格文件: {str(e)}")
            self.close()
