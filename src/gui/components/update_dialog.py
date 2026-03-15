from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QProgressBar, QTextEdit, QSizePolicy,
)
from PySide6.QtCore import Qt

from src.utils.updater import AppUpdater


class UpdateDialog(QDialog):
    """Dialog for showing update availability and download progress."""

    def __init__(self, updater: AppUpdater, version: str, download_url: str,
                 release_notes: str, parent=None):
        super().__init__(parent)
        self.updater = updater
        self.download_url = download_url
        self.setWindowTitle("软件更新")
        self.setMinimumWidth(480)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # --- State 1: Update available ---
        current = AppUpdater.get_current_version()
        self.info_label = QLabel(f"发现新版本 {version}（当前版本: v{current}）")
        self.info_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(self.info_label)

        if release_notes.strip():
            self.notes_box = QTextEdit()
            self.notes_box.setReadOnly(True)
            self.notes_box.setPlainText(release_notes)
            self.notes_box.setMaximumHeight(200)
            self.notes_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            layout.addWidget(self.notes_box)
        else:
            self.notes_box = None

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.btn_later = QPushButton("稍后再说")
        self.btn_later.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_later)

        self.btn_update = QPushButton("立即更新")
        self.btn_update.setDefault(True)
        self.btn_update.clicked.connect(self._start_download)
        btn_layout.addWidget(self.btn_update)

        layout.addLayout(btn_layout)

        # --- State 2: Downloading ---
        self.progress_label = QLabel("正在下载...")
        self.progress_label.setVisible(False)
        layout.addWidget(self.progress_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setRange(0, 100)
        layout.addWidget(self.progress_bar)

        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setVisible(False)
        self.btn_cancel.clicked.connect(self._cancel_download)
        layout.addWidget(self.btn_cancel, alignment=Qt.AlignmentFlag.AlignRight)

        # Connect updater signals
        self.updater.download_progress.connect(self._on_progress)
        self.updater.download_finished.connect(self._on_finished)
        self.updater.download_error.connect(self._on_error)

    def _start_download(self):
        """Switch to download state and start downloading."""
        self.info_label.setText("正在下载更新...")
        if self.notes_box:
            self.notes_box.setVisible(False)
        self.btn_update.setVisible(False)
        self.btn_later.setVisible(False)

        self.progress_label.setVisible(True)
        self.progress_bar.setVisible(True)
        self.btn_cancel.setVisible(True)

        self.updater.download_update(self.download_url)

    def _on_progress(self, bytes_received: int, bytes_total: int):
        if bytes_total > 0:
            self.progress_bar.setRange(0, 100)
            percent = int(bytes_received * 100 / bytes_total)
            self.progress_bar.setValue(percent)
            received_mb = bytes_received / (1024 * 1024)
            total_mb = bytes_total / (1024 * 1024)
            self.progress_label.setText(f"正在下载... {received_mb:.1f} MB / {total_mb:.1f} MB")
        else:
            self.progress_bar.setRange(0, 0)  # indeterminate
            received_mb = bytes_received / (1024 * 1024)
            self.progress_label.setText(f"正在下载... {received_mb:.1f} MB")

    def _on_finished(self, file_path: str):
        self.accept()
        AppUpdater.install_and_restart(file_path)

    def _on_error(self, error_msg: str):
        self.progress_label.setText(f"下载失败: {error_msg}")
        self.progress_bar.setVisible(False)
        self.btn_cancel.setText("关闭")

    def _cancel_download(self):
        self.updater.cancel_download()
        self.reject()
