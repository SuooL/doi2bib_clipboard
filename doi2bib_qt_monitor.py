import re
import json
import time
import threading
import requests
import pyperclip
import sys
import os
from PyQt5.QtWidgets import (QApplication, QSystemTrayIcon, QMenu, QAction,
                            QWidget, QLabel, QVBoxLayout, QHBoxLayout, QPushButton)
from PyQt5.QtGui import QIcon, QPixmap, QFont, QPainter, QColor, QBrush
from PyQt5.QtCore import Qt, QTimer, QSize, pyqtSignal, QObject, QRect
# Add to imports at the top
import keyboard


class NotificationWidget(QWidget):
    """自定义通知弹窗"""
    def __init__(self, title, message, parent=None):
        super().__init__(parent, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setStyleSheet("""
            QWidget {
                background-color: #2c3e50;
                color: white;
                border-radius: 10px;
            }
            QLabel {
                color: white;
            }
        """)

        # 设置布局
        layout = QVBoxLayout()

        # 标题
        title_label = QLabel(title)
        title_label.setFont(QFont("Arial", 12, QFont.Bold))
        layout.addWidget(title_label)

        # 消息
        message_label = QLabel(message)
        message_label.setFont(QFont("Arial", 10))
        message_label.setWordWrap(True)
        layout.addWidget(message_label)

        # 移除关闭按钮部分

        self.setLayout(layout)
        self.resize(300, 150)

        # 设置位置 - 屏幕中间靠顶部
        desktop = QApplication.desktop()
        screen_rect = desktop.availableGeometry(desktop.primaryScreen())
        # 水平居中，垂直位置在顶部下方一小段距离
        self.move(int((screen_rect.width() - self.width()) / 2),
                 int(screen_rect.height() * 0.1))  # 距离顶部约10%的位置

        # 自动关闭定时器
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.close)
        self.timer.start(5000)  # 5秒后自动关闭

    def paintEvent(self, event):
        """添加阴影效果"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QBrush(QColor(44, 62, 80)))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(QRect(0, 0, self.width(), self.height()), 10, 10)


class ClipboardSignals(QObject):
    """用于线程间通信的信号类"""
    notification = pyqtSignal(str, str)


class ClipboardMonitor:
    def __init__(self, app):
        self.app = app
        self.previous_clipboard = ""
        self.running = True
        self.signals = ClipboardSignals()
        # 添加最近查询记录
        self.recent_queries = {}
        self.query_timeout = 5  # 查询超时时间（秒）

        # Add monitoring state
        self.is_monitoring = True

        # Setup hotkeys
        self.setup_hotkeys()

        # Create tray icon
        self.create_tray_icon()

        # Connect signals
        self.signals.notification.connect(self.show_notification)

    def setup_hotkeys(self):
        """Setup global hotkeys"""
        keyboard.add_hotkey('ctrl+alt+s', self.start_monitoring)
        keyboard.add_hotkey('ctrl+alt+shift+s', self.stop_monitoring)

    def start_monitoring(self):
        """Start monitoring"""
        if not self.is_monitoring:
            self.is_monitoring = True
            self.signals.notification.emit(
                "DOI2BIB Monitor",
                "Clipboard monitoring enabled"
            )

    def stop_monitoring(self):
        """Stop monitoring"""
        if self.is_monitoring:
            self.is_monitoring = False
            self.signals.notification.emit(
                "DOI2BIB Monitor",
                "Clipboard monitoring paused"
            )

    def monitor_clipboard(self):
        """Monitor clipboard changes"""
        self.signals.notification.emit("DOI2BIB Monitor", "Started clipboard monitoring, copy text with DOI or arXiv ID to get citation")

        while self.running:
            try:
                # Check if monitoring is enabled
                if not self.is_monitoring:
                    time.sleep(1)
                    continue

                current_clipboard = pyperclip.paste()
                if current_clipboard != self.previous_clipboard:
                    self.previous_clipboard = current_clipboard

                    # 处理剪贴板内容
                    result = self.process_clipboard(current_clipboard)

                    if result["type"]:  # 如果检测到 DOI 或 arXiv ID
                        # 显示检测到的通知
                        id_type = "DOI" if result["type"] == "doi" else "arXiv"
                        self.signals.notification.emit(
                            f"检测到{id_type}",
                            f"正在获取 {result['id']} 的引用信息..."
                        )

                        # 添加短暂延迟，确保第一个通知能够显示
                        time.sleep(0.5)

                        if result["success"]:
                            # 将BibTeX写入剪贴板
                            pyperclip.copy(result["bibtex"])

                            # 显示获取成功通知
                            self.signals.notification.emit(
                                f"获取{id_type}引用成功",
                                f"已获取 {result['id']} 的BibTeX引用并复制到剪贴板"
                            )
                        else:
                            # 显示获取失败通知
                            self.signals.notification.emit(
                                "获取引用失败",
                                f"无法获取 {result['id']} 的BibTeX引用"
                            )

            except Exception as e:
                print(f"监听剪贴板时出错: {e}")
                self.signals.notification.emit(
                    "发生错误",
                    f"处理剪贴板时出错: {str(e)}"
                )

            time.sleep(1)  # 每秒检查一次

    def start(self):
        """启动监听线程"""
        self.monitor_thread = threading.Thread(target=self.monitor_clipboard)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()

    def quit(self):
        """退出应用"""
        self.running = False
        self.app.quit()


def main():
    # 创建Qt应用
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # 关闭所有窗口时不退出应用

    # 创建并启动监听器
    monitor = ClipboardMonitor(app)
    monitor.start()

    # 运行应用
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()