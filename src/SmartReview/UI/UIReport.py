# -*- coding: utf-8 -*-
# @File    : UIReport.py
# @说明    : 独立学习报告窗口: 环形图/详情表/趋势图/分布图 四个Tab, 支持导出TXT/CSV/PNG
import csv
import os
import logging
from collections import Counter, defaultdict
from datetime import datetime, date

from PyQt5.QtCore import Qt, QRectF, QPointF, QSize
from PyQt5.QtGui import QPainter, QColor, QPen, QFont, QBrush, QPainterPath
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget, QPushButton,
    QLabel, QTableWidget, QTableWidgetItem, QFileDialog, QMessageBox,
    QHeaderView, QSizePolicy, QComboBox
)

# matplotlib 为可选依赖: 未安装时使用内置 QPainter 兜底绘制
try:
    import matplotlib
    matplotlib.use('Qt5Agg')
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
    MPL_AVAILABLE = True
    # 配置中文显示字体: 按平台选择常见中文字体回退
    matplotlib.rcParams['font.sans-serif'] = [
        'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', 'SimHei',
        'Noto Sans CJK SC', 'WenQuanYi Zen Hei', 'DejaVu Sans'
    ]
    matplotlib.rcParams['axes.unicode_minus'] = False
except Exception as _e:  # pragma: no cover
    MPL_AVAILABLE = False

logger = logging.getLogger(__name__)


# 与图面板共享的掌握度配色
RANK_COLOR_HEX = {
    '精通': '#2ecc71', '掌握': '#27ae60', '记住': '#3498db', '清晰': '#5dade2',
    '模糊': '#f1c40f', '混淆': '#e67e22', '忘记': '#e74c3c', '顽固': '#8e44ad', '待定': '#95a5a6',
}


# ============================================================
# 数据聚合
# ============================================================
class ReportData(object):
    """ 从 Dictionary / LearnTactics 中聚合报告所需数据 """

    def __init__(self, book):
        self.book = book
        self.words = list(book.values())
        self.total = len(self.words)
        # 各掌握度计数
        self.rank_counts = Counter(w.rank for w in self.words)
        # 下次复习时间分布
        self.time_counts = Counter(w.review.next_review_time for w in self.words)
        # 单词详情(带排序)
        self.details = self._build_details()
        # 按日聚合趋势
        self.daily_trend = self._build_daily_trend()
        # 速度分布(直方图分箱)
        self.speed_hist = self._build_speed_hist()

    def _build_details(self):
        details = []
        for w in self.words:
            all_records = [r for batch in w.daylog.data for r in batch]  # 展平
            total = len(all_records)
            remember = sum(1 for r in all_records if r.stats)
            avg_speed = (sum(r.speed for r in all_records) / total) if total else 0.0
            details.append({
                'word': w.value,
                'explain': w.explain.replace('\n', ' ')[:60],
                'rank': w.rank,
                'total': total,
                'remember': remember,
                'forget': total - remember,
                'avg_speed': round(avg_speed, 2),
                'next_review': w.review.next_review_time,
                'associates': len(w.associate),
                'notes': (w.notes or '')[:40],
            })
        # 按掌握度优先级 + 总次数排序
        rank_order = {r: i for i, r in enumerate(
            ['精通', '掌握', '记住', '清晰', '模糊', '混淆', '忘记', '顽固', '待定'])}
        details.sort(key=lambda d: (rank_order.get(d['rank'], 99), -d['total']))
        return details

    def _build_daily_trend(self):
        """ 按日期聚合每天的记住/忘记数量与平均速度 """
        bucket = defaultdict(lambda: {'remember': 0, 'forget': 0, 'speed_sum': 0.0, 'speed_n': 0})
        for w in self.words:
            for batch in w.daylog.data:
                for rec in batch:
                    d = datetime.fromtimestamp(rec.timestamp).date().isoformat()
                    b = bucket[d]
                    if rec.stats:
                        b['remember'] += 1
                    else:
                        b['forget'] += 1
                    b['speed_sum'] += rec.speed
                    b['speed_n'] += 1
        rows = []
        for d in sorted(bucket.keys()):
            b = bucket[d]
            rows.append({
                'date': d,
                'remember': b['remember'],
                'forget': b['forget'],
                'avg_speed': round(b['speed_sum'] / b['speed_n'], 2) if b['speed_n'] else 0.0,
            })
        return rows

    def _build_speed_hist(self):
        """ 思考速度(秒)分布: 按固定区间分箱 """
        bins = [(0, 1), (1, 2), (2, 3), (3, 5), (5, 8), (8, 100)]
        labels = ['<1s', '1-2s', '2-3s', '3-5s', '5-8s', '>8s']
        counts = [0] * len(bins)
        for w in self.words:
            for batch in w.daylog.data:
                for rec in batch:
                    for i, (lo, hi) in enumerate(bins):
                        if lo <= rec.speed < hi:
                            counts[i] += 1
                            break
        return list(zip(labels, counts))

    # -------- 导出 --------
    def to_text(self):
        lines = []
        lines.append('SmartReview 学习报告')
        lines.append('生成时间: {}'.format(datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        lines.append('总词汇量: {}'.format(self.total))
        lines.append('')
        lines.append('== 掌握度分布 ==')
        for rank in ['精通', '掌握', '记住', '清晰', '模糊', '混淆', '忘记', '顽固', '待定']:
            c = self.rank_counts.get(rank, 0)
            pct = (c / self.total * 100) if self.total else 0
            lines.append('  {:<4} : {:>5}  ({:5.1f}%)'.format(rank, c, pct))
        lines.append('')
        lines.append('== 下次复习时间分布 ==')
        for k, v in sorted(self.time_counts.items(), key=lambda x: -x[1]):
            lines.append('  {:<8} : {}'.format(k, v))
        lines.append('')
        lines.append('== 最近学习趋势(按日) ==')
        for row in self.daily_trend[-30:]:
            lines.append('  {date}  记住{remember:<4} 忘记{forget:<4} 均速{avg_speed}s'.format(**row))
        return '\n'.join(lines)

    def to_csv_rows(self):
        header = ['word', 'explain', 'rank', 'total', 'remember', 'forget',
                  'avg_speed', 'next_review', 'associates', 'notes']
        rows = [header]
        for d in self.details:
            rows.append([d[k] for k in header])
        return rows


# ============================================================
# 图表画布: matplotlib 优先, QPainter 兜底
# ============================================================
class ChartCanvas(QWidget):
    """ 统一的图表承载控件,对外暴露 draw_* 与 save_png """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._mpl_canvas = None
        self._figure = None
        self._fallback = None  # FallbackCanvas

        if MPL_AVAILABLE:
            self._figure = Figure(figsize=(6, 4.5), tight_layout=True)
            self._mpl_canvas = FigureCanvasQTAgg(self._figure)
            self._mpl_canvas.setParent(self)
            lay = QVBoxLayout(self)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.addWidget(self._mpl_canvas)
        else:
            self._fallback = _FallbackCanvas(self)
            lay = QVBoxLayout(self)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.addWidget(self._fallback)

    # ---- 环形图 ----
    def draw_donut(self, label_value_pairs, title=''):
        if MPL_AVAILABLE:
            self._figure.clear()
            ax = self._figure.add_subplot(111)
            labels = [lv[0] for lv in label_value_pairs]
            sizes = [lv[1] for lv in label_value_pairs]
            colors = [RANK_COLOR_HEX.get(lb, '#95a5a6') for lb in labels]
            total = sum(sizes) or 1
            wedges, texts, autotexts = ax.pie(
                sizes, labels=labels, colors=colors, autopct=lambda p: '{:.0f}'.format(p * total / 100),
                startangle=90, wedgeprops=dict(width=0.4, edgecolor='w'))
            ax.set_title(title or '掌握度分布')
            ax.text(0, 0, '总{}'.format(total), ha='center', va='center', fontsize=14)
            ax.axis('equal')
            self._mpl_canvas.draw()
        else:
            self._fallback.set_kind('donut', label_value_pairs, title)

    # ---- 趋势折线 ----
    def draw_trend(self, rows, title=''):
        if MPL_AVAILABLE:
            self._figure.clear()
            ax = self._figure.add_subplot(111)
            dates = [r['date'][5:] for r in rows]  # MM-DD
            remember = [r['remember'] for r in rows]
            forget = [r['forget'] for r in rows]
            speed = [r['avg_speed'] for r in rows]
            x = list(range(len(rows)))
            w = 0.6
            ax.bar([i - w / 4 for i in x], remember, width=w / 2, color='#2ecc71', label='记住')
            ax.bar([i + w / 4 for i in x], forget, width=w / 2, color='#e74c3c', label='忘记')
            ax.set_xticks(x)
            ax.set_xticklabels(dates, rotation=45, fontsize=8)
            ax.set_title(title or '每日学习趋势')
            ax.legend(loc='upper left')
            ax2 = ax.twinx()
            ax2.plot(x, speed, color='#34495e', marker='o', label='均速(s)')
            ax2.set_ylabel('平均思考速度(s)')
            self._mpl_canvas.draw()
        else:
            self._fallback.set_kind('trend', rows, title)

    # ---- 分布图(柱状) ----
    def draw_distribution(self, labels, values, title='', color='#3498db'):
        if MPL_AVAILABLE:
            self._figure.clear()
            ax = self._figure.add_subplot(111)
            x = list(range(len(labels)))
            ax.bar(x, values, color=color)
            ax.set_xticks(x)
            ax.set_xticklabels(labels, rotation=20, fontsize=9)
            ax.set_title(title or '分布')
            for i, v in enumerate(values):
                ax.text(i, v, str(v), ha='center', va='bottom', fontsize=9)
            self._mpl_canvas.draw()
        else:
            self._fallback.set_kind('bar', list(zip(labels, values)), title, color)

    # ---- 时间分布(带掌握度颜色) ----
    def draw_time_distribution(self, time_counts, title=''):
        items = sorted(time_counts.items(), key=lambda x: -x[1])
        labels = [k for k, v in items]
        values = [v for k, v in items]
        self.draw_distribution(labels, values, title or '下次复习时间分布', color='#9b59b6')

    def save_png(self, path):
        if MPL_AVAILABLE and self._figure is not None:
            self._figure.savefig(path, dpi=150, bbox_inches='tight')
        else:
            pix = self.grab()
            pix.save(path, 'PNG')


# ============================================================
# Qt 原生兜底画布(matplotlib 不可用时使用)
# ============================================================
class _FallbackCanvas(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.kind = None
        self.data = []
        self.title = ''
        self.color = '#3498db'
        self.setMinimumSize(400, 300)

    def set_kind(self, kind, data, title='', color='#3498db'):
        self.kind = kind
        self.data = data or []
        self.title = title or ''
        self.color = color
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor('#ffffff'))
        if self.title:
            f = QFont(); f.setPointSize(12); f.setBold(True)
            p.setFont(f)
            p.drawText(self.rect().adjusted(0, 6, 0, 0), Qt.AlignHCenter | Qt.AlignTop, self.title)

        if not self.data:
            p.setPen(QColor('#7f8c8d'))
            p.drawText(self.rect(), Qt.AlignCenter, '无数据')
            return

        if self.kind == 'donut':
            self._draw_donut(p)
        elif self.kind == 'bar':
            self._draw_bar(p)
        elif self.kind == 'trend':
            self._draw_trend(p)

    def _draw_donut(self, p):
        rect = self.rect().adjusted(30, 40, -30, -30)
        side = min(rect.width(), rect.height())
        r = QRectF(rect.center().x() - side / 2, rect.center().y() - side / 2, side, side)
        total = sum(v for _, v in self.data) or 1
        span = 360 * 16
        start = 0
        for label, value in self.data:
            if value <= 0:
                continue
            sect = int(value / total * span)
            color = QColor(RANK_COLOR_HEX.get(label, '#95a5a6'))
            p.setBrush(QBrush(color))
            p.setPen(QPen(QColor('#ffffff'), 2))
            p.drawPie(r, start, sect)
            start += sect
        # 中间挖空形成环形
        p.setBrush(QBrush(QColor('#ffffff')))
        p.setPen(Qt.NoPen)
        inner = r.adjusted(side * 0.22, side * 0.22, -side * 0.22, -side * 0.22)
        p.drawEllipse(inner)
        p.setPen(QColor('#2c3e50'))
        f = QFont(); f.setPointSize(14); f.setBold(True)
        p.setFont(f)
        p.drawText(inner, Qt.AlignCenter, '总\n{}'.format(total))

    def _draw_bar(self, p):
        area = self.rect().adjusted(50, 50, -20, -50)
        if area.height() <= 0 or area.width() <= 0:
            return
        n = len(self.data)
        gap = 8
        bw = max(8, (area.width() - gap * (n - 1)) / max(1, n))
        maxv = max(v for _, v in self.data) or 1
        p.setPen(QColor('#2c3e50'))
        f = QFont(); f.setPointSize(8)
        p.setFont(f)
        for i, (label, value) in enumerate(self.data):
            bh = int(value / maxv * area.height())
            x = area.left() + i * (bw + gap)
            y = area.bottom() - bh
            p.setBrush(QBrush(QColor(self.color)))
            p.drawRect(QRectF(x, y, bw, bh))
            p.setPen(QColor('#2c3e50'))
            p.drawText(QRectF(x - 10, area.bottom() + 4, bw + 20, 16), Qt.AlignCenter, str(label))
            p.drawText(QRectF(x, y - 16, bw, 14), Qt.AlignCenter, str(value))

    def _draw_trend(self, p):
        area = self.rect().adjusted(50, 50, -20, -50)
        rows = self.data
        n = len(rows)
        if n == 0:
            return
        p.setPen(QColor('#2c3e50'))
        f = QFont(); f.setPointSize(8)
        p.setFont(f)
        maxv = max(max(r['remember'], r['forget']) for r in rows) or 1
        bw = max(4, area.width() / max(1, n) / 3)
        for i, r in enumerate(rows):
            cx = area.left() + area.width() * i / max(1, n - 1 if n > 1 else 1)
            rh = int(r['remember'] / maxv * area.height())
            fh = int(r['forget'] / maxv * area.height())
            p.setBrush(QBrush(QColor('#2ecc71')))
            p.drawRect(QRectF(cx - bw, area.bottom() - rh, bw, rh))
            p.setBrush(QBrush(QColor('#e74c3c')))
            p.drawRect(QRectF(cx, area.bottom() - fh, bw, fh))
            p.setPen(QColor('#2c3e50'))
            p.drawText(QPointF(cx - 14, area.bottom() + 14), r['date'][5:])


# ============================================================
# 报告主窗口
# ============================================================
class ReportDialog(QDialog):
    """ 独立报告窗口, 4 个 Tab + 导出 """

    def __init__(self, book, parent=None):
        super().__init__(parent)
        self.book = book
        self.data = ReportData(book)

        self.setWindowTitle('学习报告')
        self.resize(900, 640)

        root = QVBoxLayout(self)

        # 顶部工具栏
        topbar = QHBoxLayout()
        title = QLabel('学习报告 (共 {} 词)'.format(self.data.total))
        f = QFont(); f.setPointSize(12); f.setBold(True)
        title.setFont(f)
        topbar.addWidget(title)
        topbar.addStretch(1)

        topbar.addWidget(QLabel('导出:'))
        self.btn_txt = QPushButton('TXT')
        self.btn_txt.clicked.connect(lambda: self.export('txt'))
        topbar.addWidget(self.btn_txt)
        self.btn_csv = QPushButton('CSV')
        self.btn_csv.clicked.connect(lambda: self.export('csv'))
        topbar.addWidget(self.btn_csv)
        self.btn_png = QPushButton('PNG')
        self.btn_png.clicked.connect(lambda: self.export('png'))
        topbar.addWidget(self.btn_png)

        self.tab_combo = QComboBox()
        self.tab_combo.addItems(['环形图', '详情表', '趋势图', '分布图'])
        self.tab_combo.currentIndexChanged.connect(lambda i: self.tabs.setCurrentIndex(i))
        topbar.addWidget(QLabel('跳转到:'))
        topbar.addWidget(self.tab_combo)

        root.addLayout(topbar)

        # Tab 控件
        self.tabs = QTabWidget(self)
        root.addWidget(self.tabs, 1)

        self._build_tab_donut()
        self._build_tab_details()
        self._build_tab_trend()
        self._build_tab_distribution()

        if not MPL_AVAILABLE:
            logger.warning('matplotlib 未安装, 使用 Qt 原生绘图兜底。建议 pip install matplotlib 获得更佳效果。')

    # ---------- Tab1 环形图 ----------
    def _build_tab_donut(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        self.donut_canvas = ChartCanvas()
        lay.addWidget(self.donut_canvas)
        pairs = [(rk, self.data.rank_counts.get(rk, 0))
                 for rk in ['精通', '掌握', '记住', '清晰', '模糊', '混淆', '忘记', '顽固', '待定']
                 if self.data.rank_counts.get(rk, 0) > 0]
        self.donut_canvas.draw_donut(pairs, '掌握度环形图 (总计 {})'.format(self.data.total))
        self.tabs.addTab(w, '环形图')

    # ---------- Tab2 详情表 ----------
    def _build_tab_details(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        self.detail_table = QTableWidget()
        headers = ['单词', '释义', '掌握度', '次数', '记住', '忘记', '均速(s)', '下次复习', '关联词', '笔记']
        self.detail_table.setColumnCount(len(headers))
        self.detail_table.setHorizontalHeaderLabels(headers)
        self.detail_table.setRowCount(len(self.data.details))
        self.detail_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.detail_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.detail_table.verticalHeader().setVisible(False)
        for i, d in enumerate(self.data.details):
            row = [d['word'], d['explain'], d['rank'], d['total'], d['remember'],
                   d['forget'], d['avg_speed'], d['next_review'], d['associates'], d['notes']]
            for j, val in enumerate(row):
                item = QTableWidgetItem(str(val))
                # 按掌握度染色
                if j == 2:
                    item.setForeground(QBrush(QColor(RANK_COLOR_HEX.get(d['rank'], '#2c3e50'))))
                self.detail_table.setItem(i, j, item)
        self.detail_table.resizeColumnsToContents()
        self.detail_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        lay.addWidget(self.detail_table)
        self.tabs.addTab(w, '详情表')

    # ---------- Tab3 趋势图 ----------
    def _build_tab_trend(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        self.trend_canvas = ChartCanvas()
        lay.addWidget(self.trend_canvas)
        rows = self.data.daily_trend[-60:]
        self.trend_canvas.draw_trend(rows, '近 {} 天学习趋势'.format(len(rows)))
        self.tabs.addTab(w, '趋势图')

    # ---------- Tab4 分布图 ----------
    def _build_tab_distribution(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        self.dist_canvas = ChartCanvas()
        lay.addWidget(self.dist_canvas)
        labels, values = zip(*self.data.speed_hist) if self.data.speed_hist else ([], [])
        self.dist_canvas.draw_distribution(list(labels), list(values), '思考速度(秒)分布', color='#16a085')
        # 再加一段提示
        hint = QLabel('提示: 此 Tab 展示思考速度区间分布; 下次复习时间分布见环形图 Tab 导出数据。')
        hint.setStyleSheet('color:#7f8c8d;')
        lay.addWidget(hint)
        self.tabs.addTab(w, '分布图')

    # ---------- 导出 ----------
    def export(self, kind):
        suffix = kind.upper()
        filt = {'txt': '文本文件 (*.txt)', 'csv': 'CSV文件 (*.csv)', 'png': 'PNG图片 (*.png)'}[kind]
        default = 'smartreview_report_{}.{}'.format(datetime.now().strftime('%Y%m%d_%H%M%S'), kind)
        path, _ = QFileDialog.getSaveFileName(self, '导出{}'.format(suffix), default, filt)
        if not path:
            return
        try:
            if kind == 'txt':
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(self.data.to_text())
            elif kind == 'csv':
                with open(path, 'w', encoding='utf-8-sig', newline='') as f:
                    w = csv.writer(f)
                    for row in self.data.to_csv_rows():
                        w.writerow(row)
            elif kind == 'png':
                # 当前可见 Tab 的画布保存为 PNG
                idx = self.tabs.currentIndex()
                canvas = [self.donut_canvas, None, self.trend_canvas, self.dist_canvas][idx]
                if canvas is None:
                    # 详情表直接抓图
                    pix = self.detail_table.grab()
                    pix.save(path, 'PNG')
                else:
                    canvas.save_png(path)
            QMessageBox.information(self, '导出成功', '已导出到:\n{}'.format(path))
        except Exception as e:
            logger.exception('export failed')
            QMessageBox.critical(self, '导出失败', str(e))
