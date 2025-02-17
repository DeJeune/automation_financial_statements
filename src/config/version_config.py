import json
from pathlib import Path
from typing import Optional


class VersionConfig:
    def __init__(self):
        self.config_dir = Path("config")
        self.config_file = self.config_dir / "version.json"
        self.version = "v0.1.3"  # 默认版本

        # 确保配置目录存在
        self.config_dir.mkdir(parents=True, exist_ok=True)

        # 如果配置文件不存在，创建默认配置
        if not self.config_file.exists():
            self._create_default_config()

        self._load_config()

    def _create_default_config(self) -> None:
        """创建默认的版本配置文件"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(
                    {"version": self.version},
                    f,
                    ensure_ascii=False,
                    indent=2
                )
        except Exception as e:
            print(f"创建默认配置文件失败: {str(e)}")

    def _load_config(self) -> None:
        """加载版本配置"""
        try:
            if self.config_file.exists():
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    self.version = config.get("version", self.version)
        except Exception as e:
            print(f"加载版本配置失败: {str(e)}")

    def save_config(self) -> None:
        """保存版本配置"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(
                    {"version": self.version},
                    f,
                    ensure_ascii=False,
                    indent=2
                )
        except Exception as e:
            print(f"保存版本配置失败: {str(e)}")

    def get_version(self) -> str:
        """获取当前版本"""
        return self.version

    def set_version(self, version: str) -> None:
        """设置新版本"""
        self.version = version
        self.save_config()
