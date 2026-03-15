import json
import os
import tempfile
import re
from pathlib import Path

from PySide6.QtCore import QObject, Signal, QUrl
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from PySide6.QtWidgets import QApplication

from loguru import logger

from src._version import __version__

GITHUB_API_URL = "https://api.github.com/repos/DeJeune/automation_financial_statements/releases/latest"
ASSET_PATTERN = re.compile(r"Financial_Automation_Setup_v[\d.]+\.exe", re.IGNORECASE)


def _parse_version(version_str: str) -> tuple[int, ...]:
    """Parse a version string like 'v0.2.0' or '0.2.0' into a comparable tuple."""
    cleaned = version_str.lstrip("vV")
    parts = cleaned.split(".")
    return tuple(int(p) for p in parts)


class AppUpdater(QObject):
    update_available = Signal(str, str, str)  # (version, download_url, release_notes)
    download_progress = Signal(int, int)  # (bytes_received, bytes_total)
    download_finished = Signal(str)  # (file_path)
    download_error = Signal(str)  # (error_message)
    check_error = Signal(str)  # (error_message)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._nam = QNetworkAccessManager(self)
        self._download_reply: QNetworkReply | None = None
        self._download_path: str = ""

    @staticmethod
    def get_current_version() -> str:
        return __version__

    def check_for_updates(self):
        """Check GitHub Releases API for a newer version."""
        request = QNetworkRequest(QUrl(GITHUB_API_URL))
        request.setRawHeader(b"Accept", b"application/vnd.github.v3+json")
        request.setRawHeader(b"User-Agent", b"FinancialAutomation-Updater")

        gh_token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
        if gh_token:
            request.setRawHeader(b"Authorization", f"Bearer {gh_token}".encode())

        reply = self._nam.get(request)
        reply.finished.connect(lambda: self._on_check_finished(reply))

    def _on_check_finished(self, reply: QNetworkReply):
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                self.check_error.emit(reply.errorString())
                return

            data = json.loads(bytes(reply.readAll().data()))
            tag_name = data.get("tag_name", "")
            if not tag_name:
                self.check_error.emit("No tag_name in release response")
                return

            remote_version = _parse_version(tag_name)
            local_version = _parse_version(__version__)

            if remote_version <= local_version:
                logger.info(f"Already up to date (local={__version__}, remote={tag_name})")
                return

            # Find the installer asset
            download_url = ""
            for asset in data.get("assets", []):
                name = asset.get("name", "")
                if ASSET_PATTERN.match(name):
                    download_url = asset.get("browser_download_url", "")
                    break

            if not download_url:
                self.check_error.emit("No matching installer asset found in release")
                return

            release_notes = data.get("body", "") or ""
            self.update_available.emit(tag_name, download_url, release_notes)
        except Exception as e:
            self.check_error.emit(str(e))
        finally:
            reply.deleteLater()

    def download_update(self, url: str):
        """Download the installer to a temp directory."""
        temp_dir = tempfile.gettempdir()
        # Extract filename from URL
        filename = QUrl(url).fileName() or "Financial_Automation_Setup.exe"
        self._download_path = str(Path(temp_dir) / filename)

        request = QNetworkRequest(QUrl(url))
        request.setRawHeader(b"User-Agent", b"FinancialAutomation-Updater")
        # Follow redirects (GitHub uses redirects for asset downloads)
        request.setAttribute(
            QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy,
        )

        self._download_reply = self._nam.get(request)
        self._download_reply.downloadProgress.connect(self._on_download_progress)
        self._download_reply.finished.connect(self._on_download_finished)

    def _on_download_progress(self, bytes_received: int, bytes_total: int):
        self.download_progress.emit(bytes_received, bytes_total)

    def _on_download_finished(self):
        reply = self._download_reply
        self._download_reply = None
        if reply is None:
            return

        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                self.download_error.emit(reply.errorString())
                return

            data = reply.readAll().data()
            with open(self._download_path, "wb") as f:
                f.write(data)

            self.download_finished.emit(self._download_path)
        except Exception as e:
            self.download_error.emit(str(e))
        finally:
            reply.deleteLater()

    def cancel_download(self):
        """Abort an in-progress download."""
        if self._download_reply is not None:
            self._download_reply.abort()
            self._download_reply = None

    @staticmethod
    def install_and_restart(file_path: str):
        """Launch the downloaded installer and quit the app."""
        import subprocess

        logger.info(f"Launching installer: {file_path}")
        subprocess.Popen([file_path], shell=False)
        QApplication.quit()
