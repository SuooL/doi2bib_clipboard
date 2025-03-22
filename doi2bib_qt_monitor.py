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

        # 创建系统托盘图标
        self.create_tray_icon()

        # 连接信号到槽
        self.signals.notification.connect(self.show_notification)

    def create_tray_icon(self):
        """创建系统托盘图标和菜单"""
        # 创建菜单
        self.tray_menu = QMenu()

        # 退出动作
        quit_action = QAction("退出", self.app)
        quit_action.triggered.connect(self.quit)
        self.tray_menu.addAction(quit_action)

        # 创建系统托盘图标
        self.tray_icon = QSystemTrayIcon(self.app)
        self.tray_icon.setContextMenu(self.tray_menu)

        # 创建图标
        icon_size = 64
        pixmap = QPixmap(icon_size, icon_size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QBrush(QColor(51, 153, 255)))
        painter.setPen(QColor(255, 255, 255))
        painter.drawRect(8, 8, icon_size-16, icon_size-16)
        painter.setFont(QFont("Arial", 10, QFont.Bold))
        painter.drawText(15, 30, "DOI")
        painter.drawText(15, 45, "2BIB")
        painter.end()

        self.tray_icon.setIcon(QIcon(pixmap))
        self.tray_icon.setToolTip("DOI2BIB 监听器")
        self.tray_icon.show()

    def show_notification(self, title, message):
        """显示自定义通知弹窗"""
        self.notification_widget = NotificationWidget(title, message)
        self.notification_widget.show()

    def extract_doi(self, text):
        """匹配DOI格式，支持标准格式和纯DOI"""
        text = text.strip()
        # 支持以下格式：
        # 1. URL格式：http(s)://doi.org/10.xxxx/xxx
        # 2. 带doi:前缀：doi:10.xxxx/xxx
        # 3. 纯DOI：10.xxxx/xxx
        doi_pattern = r'^(?:https?://doi\.org/|doi:)?(10\.\d{4,}(?:\.\d+)*\/(?:(?!["&\'<>])\S)+)$'
        match = re.search(doi_pattern, text, re.IGNORECASE)
        if match:
            return match.group(1)  # 返回纯DOI部分
        return None

    def extract_arxiv(self, text):
        """匹配arXiv格式，仅支持标准格式"""
        text = text.strip()
        # 只接受以下格式：
        # 1. URL格式：https://arxiv.org/abs/2101.12345
        # 2. 带arXiv:前缀：arXiv:2101.12345
        arxiv_pattern = r'^(?:arxiv:|https?://arxiv\.org/(?:abs|pdf)/)(\d{4}\.\d{4,5}|[a-z\-]+(?:\.[A-Z]{2})?\/\d{7})$'
        match = re.search(arxiv_pattern, text, re.IGNORECASE)
        if match:
            return match.group(1)  # 返回纯ID部分
        return None

    def process_bibtex_key(self, bibtex):
        """处理BibTeX引用键，添加标题关键词"""
        # 处理引用key - 修改正则表达式以适应更宽松的格式
        key_match = re.search(r'@\w+\s*{\s*([^,\s]+)\s*,', bibtex)
        if key_match:
            old_key = key_match.group(1).strip()

            # 从标题中提取关键词 - 修改正则表达式以适应更宽松的格式
            title_match = re.search(r'title\s*=\s*[{"]([^}\"]+)[}"]', bibtex, re.IGNORECASE)
            if title_match:
                title = title_match.group(1)
                # 获取标题中的关键词（跳过常见词和短词）
                words = [w.replace('-', '') for w in re.findall(r'[\w-]+', title.lower())
                       if len(w) > 3 and w not in {
                           'with', 'from', 'using', 'based', 'this', 'that', 'and',
                           'the', 'for', 'in', 'new', 'network', 'images', 'information'
                       }]

                if words:
                    # 从前三个关键词中各取字母
                    word_parts = []
                    for word in words[:3]:
                        if len(word) >= 5:
                            # 对于较长的词，取首字母、中间字母和尾字母
                            mid_idx = len(word)//2
                            part = word[0] + word[mid_idx] + word[-1]
                        else:
                            # 对于较短的词，取首尾字母
                            part = word[0] + word[-1]
                        word_parts.append(part)

                    # 构建新的key：原key_关键词片段组合
                    suffix = '_'.join(word_parts)
                    new_key = f"{old_key}_{suffix}"

                    # 确保key只包含字母、数字和下划线
                    new_key = re.sub(r'[^a-zA-Z0-9_]', '', new_key)

                    # 替换bibtex中的key
                    return re.sub(r'(@\w+\s*{\s*)[^,\s]+(\s*,)', f'\\1{new_key}\\2', bibtex, 1)

                return bibtex

    def get_doi_bibtex(self, doi):
        """通过DOI获取BibTeX引用"""
        try:
            headers = {
                'Accept': 'application/x-bibtex',
                'User-Agent': 'DOI2BIB Clipboard Monitor'
            }
            response = requests.get(f'https://doi.org/{doi}', headers=headers)
            if response.status_code == 200:
                return self.process_bibtex_key(response.text)
            return None
        except Exception as e:
            print(f"获取DOI BibTeX失败: {e}")
            return None

    def get_arxiv_bibtex(self, arxiv_id):
        """通过arXiv ID获取BibTeX引用"""
        try:
            response = requests.get(f'http://export.arxiv.org/api/query?id_list={arxiv_id}')
            if response.status_code != 200:
                return None

            from xml.etree import ElementTree as ET
            root = ET.fromstring(response.text)

            ns = {'atom': 'http://www.w3.org/2005/Atom',
                  'arxiv': 'http://arxiv.org/schemas/atom'}

            entry = root.find('.//atom:entry', ns)
            if entry is None:
                return None

            title = entry.find('./atom:title', ns).text.strip()
            authors = [author.find('./atom:name', ns).text for author in entry.findall('./atom:author', ns)]
            published = entry.find('./atom:published', ns).text[:4]  # 只取年份
            abstract = entry.find('./atom:summary', ns).text.strip()
            url = entry.find('./atom:id', ns).text

            author_str = ' and '.join(authors)
            first_author_lastname = authors[0].split()[-1] if authors else "Unknown"
            bibtex_key = f"{first_author_lastname}{published}"

            bibtex = f"""@article{{{bibtex_key},
  title = {{{title}}},
  author = {{{author_str}}},
  year = {{{published}}},
  journal = {{arXiv preprint arXiv:{arxiv_id}}},
  url = {{{url}}},
  abstract = {{{abstract}}}
}}"""
            # 处理引用键
            return self.process_bibtex_key(bibtex)

        except Exception as e:
            print(f"获取arXiv BibTeX失败: {e}")
            return None

    def process_clipboard(self, text):
        """处理剪贴板内容，提取DOI或arXiv ID并获取BibTeX"""
        result = {"success": False, "type": None, "id": None, "bibtex": None}

        # 检查DOI
        doi = self.extract_doi(text)
        if doi:
            # 检查是否最近查询过
            current_time = time.time()
            if doi in self.recent_queries:
                last_query_time = self.recent_queries[doi]
                if current_time - last_query_time < self.query_timeout:
                    return result  # 直接返回，不进行查询

            result["type"] = "doi"
            result["id"] = doi
            bibtex = self.get_doi_bibtex(doi)
            if bibtex:
                result["bibtex"] = bibtex
                result["success"] = True
                # 记录查询时间
                self.recent_queries[doi] = current_time
                return result

        # 检查arXiv
        arxiv_id = self.extract_arxiv(text)
        if arxiv_id:
            result["type"] = "arxiv"
            result["id"] = arxiv_id
            bibtex = self.get_arxiv_bibtex(arxiv_id)
            if bibtex:
                result["bibtex"] = bibtex
                result["success"] = True
                return result

        return result

    def monitor_clipboard(self):
        """监听剪贴板变化的线程函数"""
        # 显示启动通知
        self.signals.notification.emit("DOI2BIB 监听器", "已启动剪贴板监听，复制包含DOI或arXiv ID的文本即可获取引用")

        while self.running:
            try:
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
