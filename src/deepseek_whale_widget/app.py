"""入口：uv run dsh-whale-widget 或 python -m deepseek_whale_widget。"""
from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication

from .widget import WhaleWidget


def main() -> int:
    app = QApplication([])
    app.setApplicationName("DeepSeek Whale Widget (PyQt)")
    app.setApplicationDisplayName("DeepSeek 小鲸鱼余额挂件")
    app.setQuitOnLastWindowClosed(True)
    widget = WhaleWidget()
    widget.show()
    widget.refresh(False)  # 启动即拉一次余额
    return app.exec()
