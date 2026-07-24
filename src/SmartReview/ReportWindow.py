# -*- coding: utf-8 -*-
# @File    : ReportWindow.py
# @Description: 独立报告窗口 - 从DayLog聚合数据，四Tab展示环形图/详情表/趋势图/分布图
import os
import csv
import logging
from datetime import datetime, timedelta
from collections import Counter, defaultdict

from PyQt5.QtCore import Qt, QPoint
from PyQt5.QtGui import QFont, QPixmap, QPainter, QRegion
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget, QPushButton,
    QLabel, QTableWidget, QTableWidgetItem, QHeaderView, QFileDialog,
    QMessageBox, QTextEdit, QSplitter, QGroupBox
)

# matplotlib配置 - 必须在其他matplotlib导入之前设置
import matplotlib
matplotlib.use('Qt5Agg')
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

logger = logging.getLogger(__name__)

# 设置matplotlib中文字体
def _setup_chinese_font():
    """配置matplotlib中文字体支持"""
    font_candidates = [
        'PingFang SC', 'Heiti SC', 'STHeiti', 'SimHei',
        'Microsoft YaHei', 'WenQuanYi Micro Hei', 'Arial Unicode MS'
    ]
    available_fonts = set(f.name for f in fm.fontManager.ttflist)
    for font_name in font_candidates:
        if font_name in available_fonts:
            plt.rcParams['font.sans-serif'] = [font_name, 'DejaVu Sans']
            plt.rcParams['axes.unicode_minus'] = False
            logger.info('matplotlib使用字体: {}'.format(font_name))
            return
    logger.warning('未找到中文字体，图表中文可能显示异常')

_setup_chinese_font()


class MatplotlibCanvas(FigureCanvas):
    """matplotlib画布基类 - 封装到Qt Widget"""

    def __init__(self, parent=None, width=8, height=6, dpi=100):
        self.fig = Figure(figsize=(width, height), dpi=dpi, tight_layout=True)
        super().__init__(self.fig)
        self.setParent(parent)


class DonutChartTab(QWidget):
    """Tab1: 环形图 - 展示当前掌握度分布"""

    def __init__(self, dictionary, parent=None):
        super().__init__(parent)
        self.dictionary = dictionary
        self._setup_ui()
        self._draw_chart()

    def _setup_ui(self):
        """设置UI"""
        layout = QVBoxLayout(self)
        self.canvas = MatplotlibCanvas(self, width=8, height=6)
        layout.addWidget(self.canvas)

    def _draw_chart(self):
        """绘制环形图"""
        self.canvas.fig.clear()
        ax = self.canvas.fig.add_subplot(111)

        # 获取掌握度统计
        ranks = self.dictionary.info_ranks
        if not ranks:
            ax.text(0.5, 0.5, '暂无数据', ha='center', va='center', fontsize=20)
            self.canvas.draw()
            return

        # 准备数据
        labels = list(ranks.keys())
        sizes = list(ranks.values())
        total = sum(sizes)

        # 颜色映射（与GraphPanel一致）
        color_map = {
            '精通': '#2ecc71', '掌握': '#3498db', '记住': '#9b59b6',
            '清晰': '#1abc9c', '模糊': '#f1c40f', '混淆': '#e67e22',
            '忘记': '#e74c3c', '顽固': '#c0392b', '待定': '#95a5a6'
        }
        colors = [color_map.get(label, '#95a5a6') for label in labels]

        # 绘制环形图
        wedges, texts, autotexts = ax.pie(
            sizes, labels=labels, colors=colors, autopct='%1.1f%%',
            startangle=90, pctdistance=0.82,
            wedgeprops=dict(width=0.4, edgecolor='white', linewidth=2)
        )

        # 设置文字样式
        for text in texts:
            text.set_fontsize(11)
        for autotext in autotexts:
            autotext.set_fontsize(9)
            autotext.set_color('white')
            autotext.set_fontweight('bold')

        # 中心文字
        ax.text(0, 0, '总计\n{}词'.format(total), ha='center', va='center',
                fontsize=16, fontweight='bold')

        ax.set_title('单词掌握度分布', fontsize=14, fontweight='bold', pad=20)
        ax.axis('equal')

        self.canvas.draw()

    def refresh(self, dictionary):
        """刷新数据"""
        self.dictionary = dictionary
        self._draw_chart()

    def get_figure(self):
        """获取matplotlib figure对象（用于导出）"""
        return self.canvas.fig


class DetailTableTab(QWidget):
    """Tab2: 详情表 - 展示所有单词详细信息"""

    def __init__(self, dictionary, parent=None):
        super().__init__(parent)
        self.dictionary = dictionary
        self._setup_ui()
        self._populate_table()

    def _setup_ui(self):
        """设置UI"""
        layout = QVBoxLayout(self)

        # 统计信息标签
        self.stats_label = QLabel()
        self.stats_label.setFont(QFont('Arial', 11))
        layout.addWidget(self.stats_label)

        # 表格
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(
            ['单词', '掌握度', '关联数', '复习次数', '最近复习时间', '下次复习']
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSortingEnabled(True)
        layout.addWidget(self.table)

    def _populate_table(self):
        """填充表格数据"""
        words = sorted(self.dictionary.values(), key=lambda w: w.priority)
        self.table.setRowCount(len(words))

        remember_count = 0
        forget_count = 0

        for row, word in enumerate(words):
            self.table.setItem(row, 0, QTableWidgetItem(word.value))
            self.table.setItem(row, 1, QTableWidgetItem(word.rank))
            self.table.setItem(row, 2, QTableWidgetItem(str(len(word.associate))))

            # 复习次数（所有日志记录数之和）
            total_reviews = sum(len(records) for records in word.daylog.data)
            self.table.setItem(row, 3, QTableWidgetItem(str(total_reviews)))

            # 最近复习时间
            try:
                last_ts = word.daylog.last_records[-1].timestamp
                last_time = datetime.fromtimestamp(last_ts).strftime('%Y-%m-%d %H:%M')
            except Exception:
                last_time = '从未'
            self.table.setItem(row, 4, QTableWidgetItem(last_time))

            # 下次复习时间
            next_review = word.review.next_review_time
            self.table.setItem(row, 5, QTableWidgetItem(next_review))

            # 统计
            if word.rank in ('精通', '掌握', '记住', '清晰'):
                remember_count += 1
            else:
                forget_count += 1

        # 统计信息
        total = len(words)
        rate = (remember_count / total * 100) if total > 0 else 0
        self.stats_label.setText(
            '总词汇量: {} | 已掌握: {} | 需复习: {} | 正确率: {:.1f}%'.format(
                total, remember_count, forget_count, rate
            )
        )

    def refresh(self, dictionary):
        """刷新数据"""
        self.dictionary = dictionary
        self._populate_table()

    def save_as_png(self, filepath):
        """将详情表导出为PNG图片（包含全部行，非仅可见区域）"""
        row_count = self.table.rowCount()
        col_count = self.table.columnCount()
        if row_count == 0:
            return

        # 获取行高和列宽
        row_height = self.table.rowHeight(0) if row_count > 0 else 30
        header_height = self.table.horizontalHeader().height()
        total_width = self.table.verticalHeader().width() + 40
        for col in range(col_count):
            total_width += self.table.columnWidth(col)

        # 限制最大行数避免生成过大图片
        max_rows = min(row_count, 500)
        render_height = header_height + max_rows * row_height + 2

        # 创建pixmap（上方留50px给统计标签）
        pixmap = QPixmap(total_width, render_height + 50)
        pixmap.fill(Qt.white)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)

        # 渲染统计标签到顶部
        self.stats_label.render(painter, targetOffset=QPoint(10, 5))

        # 渲染表格（下移40px给标签留出空间）
        painter.translate(0, 40)
        self.table.render(painter, QRegion(0, 0, total_width, render_height))
        painter.end()

        pixmap.save(filepath, 'PNG')
        if row_count > max_rows:
            logger.info('表格有{}行，仅导出前{}行'.format(row_count, max_rows))

    def export_csv(self, filepath):
        """导出CSV"""
        with open(filepath, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(['单词', '掌握度', '关联数', '复习次数', '最近复习时间', '下次复习'])
            for row in range(self.table.rowCount()):
                row_data = []
                for col in range(self.table.columnCount()):
                    item = self.table.item(row, col)
                    row_data.append(item.text() if item else '')
                writer.writerow(row_data)

    def export_txt(self, filepath):
        """导出TXT"""
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(self.stats_label.text() + '\n')
            f.write('=' * 80 + '\n')
            f.write('{:<20} {:<8} {:<8} {:<8} {:<20} {:<10}\n'.format(
                '单词', '掌握度', '关联数', '复习次数', '最近复习', '下次复习'
            ))
            f.write('-' * 80 + '\n')
            for row in range(self.table.rowCount()):
                word = self.table.item(row, 0).text() if self.table.item(row, 0) else ''
                rank = self.table.item(row, 1).text() if self.table.item(row, 1) else ''
                assoc = self.table.item(row, 2).text() if self.table.item(row, 2) else ''
                reviews = self.table.item(row, 3).text() if self.table.item(row, 3) else ''
                last = self.table.item(row, 4).text() if self.table.item(row, 4) else ''
                next_r = self.table.item(row, 5).text() if self.table.item(row, 5) else ''
                f.write('{:<20} {:<8} {:<8} {:<8} {:<20} {:<10}\n'.format(
                    word, rank, assoc, reviews, last, next_r
                ))


class TrendChartTab(QWidget):
    """Tab3: 趋势图 - 展示历史学习趋势"""

    def __init__(self, dictionary, parent=None):
        super().__init__(parent)
        self.dictionary = dictionary
        self._setup_ui()
        self._draw_chart()

    def _setup_ui(self):
        """设置UI"""
        layout = QVBoxLayout(self)
        self.canvas = MatplotlibCanvas(self, width=8, height=6)
        self.toolbar = NavigationToolbar(self.canvas, self)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas)

    def _collect_trend_data(self):
        """从所有单词的DayLog中收集历史趋势数据"""
        # 按日期聚合每天的正确/错误数
        daily_stats = defaultdict(lambda: {'correct': 0, 'wrong': 0, 'total': 0})

        for word in self.dictionary.values():
            for session_records in word.daylog.data:
                if not session_records:
                    continue
                # 使用session中最后一个record的时间戳作为日期
                session_date = datetime.fromtimestamp(
                    session_records[-1].timestamp
                ).strftime('%Y-%m-%d')
                for record in session_records:
                    daily_stats[session_date]['total'] += 1
                    if record.stats:
                        daily_stats[session_date]['correct'] += 1
                    else:
                        daily_stats[session_date]['wrong'] += 1

        return daily_stats

    def _draw_chart(self):
        """绘制趋势图"""
        self.canvas.fig.clear()
        ax = self.canvas.fig.add_subplot(111)

        daily_stats = self._collect_trend_data()
        if not daily_stats:
            ax.text(0.5, 0.5, '暂无历史数据\n完成至少一次复习后可查看趋势',
                    ha='center', va='center', fontsize=14, color='gray')
            self.canvas.draw()
            return

        # 排序日期
        sorted_dates = sorted(daily_stats.keys())
        dates = sorted_dates[-30:]  # 最近30天
        correct_counts = [daily_stats[d]['correct'] for d in dates]
        wrong_counts = [daily_stats[d]['wrong'] for d in dates]
        total_counts = [daily_stats[d]['total'] for d in dates]
        accuracy = []
        for c, w in zip(correct_counts, wrong_counts):
            total = c + w
            accuracy.append((c / total * 100) if total > 0 else 0)

        # 绘制柱状图
        x = range(len(dates))
        width = 0.35
        ax.bar([i - width/2 for i in x], correct_counts, width,
               label='记住', color='#2ecc71', alpha=0.8)
        ax.bar([i + width/2 for i in x], wrong_counts, width,
               label='忘记', color='#e74c3c', alpha=0.8)

        # 绘制正确率折线
        ax2 = ax.twinx()
        ax2.plot(x, accuracy, 'b-o', linewidth=2, markersize=4, label='正确率')
        ax2.set_ylabel('正确率 (%)', color='blue', fontsize=11)
        ax2.set_ylim(0, 110)
        ax2.tick_params(axis='y', labelcolor='blue')

        # 设置x轴标签
        ax.set_xticks(x)
        short_dates = [d[5:] for d in dates]  # 只显示月-日
        ax.set_xticklabels(short_dates, rotation=45, ha='right', fontsize=8)

        ax.set_xlabel('日期', fontsize=11)
        ax.set_ylabel('单词数', fontsize=11)
        ax.set_title('学习趋势图（最近{}天）'.format(len(dates)), fontsize=14, fontweight='bold')
        ax.legend(loc='upper left')
        ax2.legend(loc='upper right')
        ax.grid(axis='y', alpha=0.3)

        self.canvas.fig.tight_layout()
        self.canvas.draw()

    def refresh(self, dictionary):
        """刷新数据"""
        self.dictionary = dictionary
        self._draw_chart()

    def get_figure(self):
        """获取matplotlib figure对象"""
        return self.canvas.fig


class DistributionChartTab(QWidget):
    """Tab4: 分布图 - 展示单词长度分布和首字母分布"""

    def __init__(self, dictionary, parent=None):
        super().__init__(parent)
        self.dictionary = dictionary
        self._setup_ui()
        self._draw_chart()

    def _setup_ui(self):
        """设置UI"""
        layout = QVBoxLayout(self)
        self.canvas = MatplotlibCanvas(self, width=8, height=6)
        self.toolbar = NavigationToolbar(self.canvas, self)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas)

    def _draw_chart(self):
        """绘制分布图"""
        self.canvas.fig.clear()

        words = list(self.dictionary.values())
        if not words:
            ax = self.canvas.fig.add_subplot(111)
            ax.text(0.5, 0.5, '暂无数据', ha='center', va='center', fontsize=20)
            self.canvas.draw()
            return

        # 子图1: 单词长度分布
        ax1 = self.canvas.fig.add_subplot(121)
        word_lengths = [len(w.value) for w in words]
        length_counter = Counter(word_lengths)
        lengths = sorted(length_counter.keys())
        counts_l = [length_counter[l] for l in lengths]

        bars = ax1.bar(lengths, counts_l, color='#3498db', alpha=0.8, edgecolor='white')
        ax1.set_xlabel('单词长度（字母数）', fontsize=10)
        ax1.set_ylabel('单词数量', fontsize=10)
        ax1.set_title('单词长度分布', fontsize=12, fontweight='bold')
        ax1.grid(axis='y', alpha=0.3)

        # 在柱子上标注数值
        for bar, count in zip(bars, counts_l):
            ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.3,
                     str(count), ha='center', va='bottom', fontsize=8)

        # 子图2: 首字母分布
        ax2 = self.canvas.fig.add_subplot(122)
        first_letters = [w.value[0].upper() for w in words]
        letter_counter = Counter(first_letters)
        # 按A-Z排序
        all_letters = sorted(letter_counter.keys())
        counts_f = [letter_counter[l] for l in all_letters]

        color_map = plt.cm.Set3(range(len(all_letters)))
        ax2.bar(all_letters, counts_f, color=color_map, alpha=0.8, edgecolor='white')
        ax2.set_xlabel('首字母', fontsize=10)
        ax2.set_ylabel('单词数量', fontsize=10)
        ax2.set_title('首字母分布', fontsize=12, fontweight='bold')
        ax2.grid(axis='y', alpha=0.3)
        plt.setp(ax2.get_xticklabels(), fontsize=8)

        self.canvas.fig.tight_layout()
        self.canvas.draw()

    def refresh(self, dictionary):
        """刷新数据"""
        self.dictionary = dictionary
        self._draw_chart()

    def get_figure(self):
        """获取matplotlib figure对象"""
        return self.canvas.fig


class ReportWindow(QDialog):
    """独立报告窗口 - 集成四个Tab的报告展示"""

    def __init__(self, dictionary, parent=None):
        super().__init__(parent)
        self.dictionary = dictionary
        self.setWindowTitle('学习报告 - SmartReview 数据分析')
        self.resize(1100, 750)
        self._setup_ui()

    def _setup_ui(self):
        """设置UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        # 顶部标题栏
        header_layout = QHBoxLayout()
        title_label = QLabel('📊 SmartReview 学习报告')
        title_label.setFont(QFont('Arial', 16, QFont.Bold))
        header_layout.addWidget(title_label)
        header_layout.addStretch()

        # 导出按钮
        self.btn_export_txt = QPushButton('导出TXT')
        self.btn_export_csv = QPushButton('导出CSV')
        self.btn_export_png = QPushButton('导出PNG')
        self.btn_refresh = QPushButton('刷新数据')

        self.btn_export_txt.clicked.connect(self._export_txt)
        self.btn_export_csv.clicked.connect(self._export_csv)
        self.btn_export_png.clicked.connect(self._export_png)
        self.btn_refresh.clicked.connect(self._refresh)

        header_layout.addWidget(self.btn_refresh)
        header_layout.addWidget(self.btn_export_txt)
        header_layout.addWidget(self.btn_export_csv)
        header_layout.addWidget(self.btn_export_png)
        layout.addLayout(header_layout)

        # Tab Widget
        self.tabs = QTabWidget()

        # 创建四个Tab
        self.tab_donut = DonutChartTab(self.dictionary)
        self.tab_detail = DetailTableTab(self.dictionary)
        self.tab_trend = TrendChartTab(self.dictionary)
        self.tab_dist = DistributionChartTab(self.dictionary)

        self.tabs.addTab(self.tab_donut, '🍩 掌握度环形图')
        self.tabs.addTab(self.tab_detail, '📋 详细数据表')
        self.tabs.addTab(self.tab_trend, '📈 学习趋势图')
        self.tabs.addTab(self.tab_dist, '📊 单词分布图')

        layout.addWidget(self.tabs)

        # 底部时间戳
        footer = QLabel('报告生成时间: {}'.format(
            datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        ))
        footer.setStyleSheet('color: gray; font-size: 10px;')
        footer.setAlignment(Qt.AlignRight)
        layout.addWidget(footer)

    def _refresh(self):
        """刷新所有Tab数据"""
        self.tab_donut.refresh(self.dictionary)
        self.tab_detail.refresh(self.dictionary)
        self.tab_trend.refresh(self.dictionary)
        self.tab_dist.refresh(self.dictionary)

    def _export_txt(self):
        """导出TXT报告"""
        filepath, _ = QFileDialog.getSaveFileName(
            self, '导出TXT报告',
            'SmartReview报告_{}.txt'.format(datetime.now().strftime('%Y%m%d_%H%M%S')),
            '文本文件 (*.txt)'
        )
        if filepath:
            try:
                self.tab_detail.export_txt(filepath)
                QMessageBox.information(self, '导出成功', '报告已导出到:\n{}'.format(filepath))
            except Exception as e:
                QMessageBox.warning(self, '导出失败', str(e))

    def _export_csv(self):
        """导出CSV数据表"""
        filepath, _ = QFileDialog.getSaveFileName(
            self, '导出CSV数据',
            'SmartReview数据_{}.csv'.format(datetime.now().strftime('%Y%m%d_%H%M%S')),
            'CSV文件 (*.csv)'
        )
        if filepath:
            try:
                self.tab_detail.export_csv(filepath)
                QMessageBox.information(self, '导出成功', '数据已导出到:\n{}'.format(filepath))
            except Exception as e:
                QMessageBox.warning(self, '导出失败', str(e))

    def _export_png(self):
        """导出当前Tab的PNG图片"""
        filepath, _ = QFileDialog.getSaveFileName(
            self, '导出PNG图片',
            'SmartReview图表_{}.png'.format(datetime.now().strftime('%Y%m%d_%H%M%S')),
            'PNG图片 (*.png)'
        )
        if filepath:
            try:
                current_tab = self.tabs.currentWidget()
                if hasattr(current_tab, 'save_as_png'):
                    # QWidget类Tab（如详情表）使用自身的渲染方法
                    current_tab.save_as_png(filepath)
                    QMessageBox.information(self, '导出成功', '图片已导出到:\n{}'.format(filepath))
                elif hasattr(current_tab, 'get_figure'):
                    # matplotlib图表Tab
                    current_tab.get_figure().savefig(filepath, dpi=150, bbox_inches='tight')
                    QMessageBox.information(self, '导出成功', '图片已导出到:\n{}'.format(filepath))
                else:
                    QMessageBox.information(self, '提示', '当前Tab不支持图片导出')
            except Exception as e:
                QMessageBox.warning(self, '导出失败', str(e))
