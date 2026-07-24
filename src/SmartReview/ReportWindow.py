# -*- coding: utf-8 -*-
# @File    : ReportWindow.py
# @Desc    : 独立统计报告窗口。
#
# 需求 2:将 ESC 触发的简陋文字统计升级为独立报告窗口。
#   - 从每个 Vocabulary 的 DayLog 聚合数据;
#   - 四个 Tab 分别展示:
#       1) 环形图(掌握度占比)
#       2) 详情表(逐词统计:掌握度 / 复习次数 / 正确率 / 平均思考耗时 / 下次复习)
#       3) 趋势图(按天统计复习量与正确率的折线)
#       4) 分布图(思考耗时直方图 + 各掌握度柱状分布)
#   - 支持导出 TXT / CSV / PNG。
from collections import Counter, defaultdict
from datetime import datetime

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QTableWidget,
    QTableWidgetItem, QPushButton, QFileDialog, QMessageBox, QLabel,
)

# matplotlib 嵌入 Qt
import matplotlib
matplotlib.use('Qt5Agg')  # 使用 Qt5 后端
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

# 让 matplotlib 正常显示中文,避免方块
matplotlib.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'PingFang SC',
                                          'Heiti SC', 'SimHei', 'sans-serif']
matplotlib.rcParams['axes.unicode_minus'] = False

from SmartReview import Palette


class MplCanvas(FigureCanvas):
    """ 一个可复用的 matplotlib 画布控件 """

    def __init__(self, width=6, height=4):
        self.fig = Figure(figsize=(width, height), tight_layout=True)
        super(MplCanvas, self).__init__(self.fig)


class ReportWindow(QWidget):
    """ 复习统计报告窗口 """

    def __init__(self, book, parent=None):
        super(ReportWindow, self).__init__(parent)
        self.book = book
        self.setWindowTitle('复习统计报告')
        self.resize(880, 640)

        # 聚合后的数据缓存(供导出复用)
        self._rank_counter = Counter()
        self._detail_rows = []            # [(word, rank, times, accuracy, avg_speed, next_review)]
        self._daily = {}                  # date_str -> (review_count, accuracy)
        self._speeds = []                 # 所有思考耗时

        layout = QVBoxLayout(self)

        # Tab 容器
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # 四个画布 / 表格
        self.ringCanvas = MplCanvas()
        self.detailTable = QTableWidget()
        self.trendCanvas = MplCanvas()
        self.distCanvas = MplCanvas()

        self.tabs.addTab(self.ringCanvas, '掌握度环形图')
        self.tabs.addTab(self.detailTable, '单词详情表')
        self.tabs.addTab(self.trendCanvas, '复习趋势图')
        self.tabs.addTab(self.distCanvas, '数据分布图')

        # 底部导出按钮
        btnbar = QHBoxLayout()
        self.summaryLabel = QLabel('')
        btnbar.addWidget(self.summaryLabel)
        btnbar.addStretch()
        self.exportTxtBtn = QPushButton('导出 TXT')
        self.exportCsvBtn = QPushButton('导出 CSV')
        self.exportPngBtn = QPushButton('导出 PNG(当前图)')
        btnbar.addWidget(self.exportTxtBtn)
        btnbar.addWidget(self.exportCsvBtn)
        btnbar.addWidget(self.exportPngBtn)
        layout.addLayout(btnbar)

        self.exportTxtBtn.clicked.connect(self.export_txt)
        self.exportCsvBtn.clicked.connect(self.export_csv)
        self.exportPngBtn.clicked.connect(self.export_png)

    # ------------------------------------------------------------------
    #  数据聚合
    # ------------------------------------------------------------------
    def _aggregate(self):
        """ 从词书中的 DayLog 聚合出各图表所需的数据 """
        self._rank_counter = Counter()
        self._detail_rows = []
        self._speeds = []
        daily_total = defaultdict(int)     # 每天复习次数
        daily_correct = defaultdict(int)   # 每天记住次数

        for word_obj in self.book.values():
            rank = word_obj.rank
            self._rank_counter[rank] += 1

            # 展开该词所有历史记录(DayLog 是"多次背词"的二级列表)
            all_records = []
            for day_records in word_obj.daylog.data:
                all_records.extend(day_records)
            # 也包含尚未落盘的本次记录
            all_records.extend(word_obj.daylog.records_lst)

            times = len(all_records)
            correct = sum(1 for r in all_records if r.stats is True)
            accuracy = (correct / times * 100) if times else 0.0
            speeds = [r.speed for r in all_records if r.speed is not None]
            avg_speed = (sum(speeds) / len(speeds)) if speeds else 0.0
            self._speeds.extend(speeds)

            self._detail_rows.append((
                word_obj.value, rank, times,
                round(accuracy, 1), round(avg_speed, 2),
                word_obj.review.next_review_time,
            ))

            # 按日期归并趋势
            for r in all_records:
                try:
                    day = datetime.fromtimestamp(r.timestamp).strftime('%Y-%m-%d')
                except (OSError, ValueError, OverflowError):
                    continue
                daily_total[day] += 1
                if r.stats is True:
                    daily_correct[day] += 1

        # 计算每日正确率
        self._daily = {}
        for day in sorted(daily_total):
            total = daily_total[day]
            acc = (daily_correct[day] / total * 100) if total else 0.0
            self._daily[day] = (total, acc)

    # ------------------------------------------------------------------
    #  绘制各 Tab
    # ------------------------------------------------------------------
    def refresh(self):
        """ 重新聚合数据并刷新四个 Tab """
        self._aggregate()
        self._draw_ring()
        self._fill_detail_table()
        self._draw_trend()
        self._draw_distribution()

        total = sum(self._rank_counter.values())
        self.summaryLabel.setText('共 {} 个单词 | 累计复习记录 {} 条'
                                  .format(total, len(self._speeds)))

    def _draw_ring(self):
        """ Tab1:掌握度占比环形图(donut) """
        fig = self.ringCanvas.fig
        fig.clear()
        ax = fig.add_subplot(111)
        # 按语义顺序排列,过滤掉数量为 0 的
        labels, sizes, colors = [], [], []
        for rank in Palette.ordered_ranks():
            cnt = self._rank_counter.get(rank, 0)
            if cnt > 0:
                labels.append('{} ({})'.format(rank, cnt))
                sizes.append(cnt)
                colors.append(Palette.color_of(rank))
        if sizes:
            ax.pie(sizes, labels=labels, colors=colors, autopct='%1.1f%%',
                   startangle=90, pctdistance=0.8,
                   wedgeprops=dict(width=0.4, edgecolor='white'))  # width<1 形成环形
            ax.set_title('单词掌握度分布')
        else:
            ax.text(0.5, 0.5, '暂无数据', ha='center', va='center')
        ax.axis('equal')
        self.ringCanvas.draw()

    def _fill_detail_table(self):
        """ Tab2:逐词详情表 """
        headers = ['单词', '掌握度', '复习次数', '正确率(%)', '平均思考(s)', '下次复习']
        table = self.detailTable
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setRowCount(len(self._detail_rows))
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSortingEnabled(False)  # 填充时先关闭排序,避免错位
        # 按掌握度优先级排序,顽固/忘记的排在前面便于关注
        order = {r: i for i, r in enumerate(Palette.ordered_ranks())}
        rows = sorted(self._detail_rows, key=lambda x: order.get(x[1], 99), reverse=True)
        for i, row in enumerate(rows):
            for j, val in enumerate(row):
                item = QTableWidgetItem(str(val))
                if j == 1:  # 掌握度列上色
                    item.setBackground(Qt.transparent)
                    from PyQt5.QtGui import QColor
                    item.setForeground(QColor(Palette.color_of(val)))
                table.setItem(i, j, item)
        table.resizeColumnsToContents()
        table.setSortingEnabled(True)

    def _draw_trend(self):
        """ Tab3:复习量与正确率趋势折线 """
        fig = self.trendCanvas.fig
        fig.clear()
        ax = fig.add_subplot(111)
        if self._daily:
            days = list(self._daily.keys())
            counts = [self._daily[d][0] for d in days]
            accs = [self._daily[d][1] for d in days]
            ax.plot(days, counts, marker='o', color='#42A5F5', label='复习次数')
            ax.set_ylabel('复习次数', color='#42A5F5')
            ax.tick_params(axis='x', rotation=45)
            # 次坐标轴画正确率
            ax2 = ax.twinx()
            ax2.plot(days, accs, marker='s', color='#66BB6A', label='正确率(%)')
            ax2.set_ylabel('正确率(%)', color='#66BB6A')
            ax2.set_ylim(0, 105)
            ax.set_title('每日复习趋势')
        else:
            ax.text(0.5, 0.5, '暂无复习记录', ha='center', va='center')
        self.trendCanvas.draw()

    def _draw_distribution(self):
        """ Tab4:思考耗时直方图 + 掌握度柱状分布 """
        fig = self.distCanvas.fig
        fig.clear()
        ax1 = fig.add_subplot(121)
        ax2 = fig.add_subplot(122)

        # 左:思考耗时直方图
        if self._speeds:
            # 过滤掉异常大的耗时(比如中途离开),只看 0~10s
            data = [s for s in self._speeds if 0 <= s <= 10]
            ax1.hist(data or self._speeds, bins=15, color='#7E57C2', edgecolor='white')
            ax1.set_title('思考耗时分布')
            ax1.set_xlabel('耗时(s)')
            ax1.set_ylabel('次数')
        else:
            ax1.text(0.5, 0.5, '暂无耗时数据', ha='center', va='center')

        # 右:各掌握度柱状分布
        ranks, counts, colors = [], [], []
        for rank in Palette.ordered_ranks():
            cnt = self._rank_counter.get(rank, 0)
            if cnt > 0:
                ranks.append(rank)
                counts.append(cnt)
                colors.append(Palette.color_of(rank))
        if counts:
            ax2.bar(ranks, counts, color=colors)
            ax2.set_title('各掌握度单词数')
            ax2.tick_params(axis='x', rotation=45)
        else:
            ax2.text(0.5, 0.5, '暂无数据', ha='center', va='center')

        self.distCanvas.draw()

    # ------------------------------------------------------------------
    #  显示 & 导出
    # ------------------------------------------------------------------
    def show(self):
        self.refresh()
        super(ReportWindow, self).show()
        self.raise_()
        self.activateWindow()

    def export_txt(self):
        """ 导出为纯文本摘要 """
        path, _ = QFileDialog.getSaveFileName(self, '导出 TXT', 'report.txt',
                                              'Text Files (*.txt)')
        if not path:
            return
        lines = ['SmartReview 复习统计报告',
                 '生成时间: {}'.format(datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
                 '=' * 40, '【掌握度分布】']
        for rank in Palette.ordered_ranks():
            cnt = self._rank_counter.get(rank, 0)
            if cnt:
                lines.append('  {}: {}'.format(rank, cnt))
        lines.append('=' * 40)
        lines.append('【每日复习趋势】')
        for day, (cnt, acc) in self._daily.items():
            lines.append('  {}: 复习 {} 次, 正确率 {:.1f}%'.format(day, cnt, acc))
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))
            QMessageBox.information(self, '导出成功', '已保存到:\n{}'.format(path))
        except OSError as e:
            QMessageBox.warning(self, '导出失败', str(e))

    def export_csv(self):
        """ 导出逐词详情表为 CSV """
        path, _ = QFileDialog.getSaveFileName(self, '导出 CSV', 'report.csv',
                                              'CSV Files (*.csv)')
        if not path:
            return
        import csv
        try:
            with open(path, 'w', encoding='utf-8-sig', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['单词', '掌握度', '复习次数', '正确率(%)',
                                 '平均思考(s)', '下次复习'])
                writer.writerows(self._detail_rows)
            QMessageBox.information(self, '导出成功', '已保存到:\n{}'.format(path))
        except OSError as e:
            QMessageBox.warning(self, '导出失败', str(e))

    def export_png(self):
        """ 导出当前 Tab 为 PNG。
        图表 Tab 直接保存对应画布;详情表 Tab 则把表格数据渲染成一张表格图片。 """
        idx = self.tabs.currentIndex()
        path, _ = QFileDialog.getSaveFileName(self, '导出 PNG', 'chart.png',
                                              'PNG Files (*.png)')
        if not path:
            return
        try:
            if idx == 1:
                # 详情表 Tab:用 matplotlib 把表格数据绘制成表格图片
                self._export_table_png(path)
            else:
                # 其余三个 Tab 都是 matplotlib 画布,直接保存
                canvas_map = {0: self.ringCanvas, 2: self.trendCanvas, 3: self.distCanvas}
                canvas_map[idx].fig.savefig(path, dpi=150)
            QMessageBox.information(self, '导出成功', '已保存到:\n{}'.format(path))
        except OSError as e:
            QMessageBox.warning(self, '导出失败', str(e))

    def _export_table_png(self, path):
        """ 将详情表渲染为表格图片并保存到 path """
        headers = ['单词', '掌握度', '复习次数', '正确率(%)', '平均思考(s)', '下次复习']
        # 按掌握度优先级排序,与界面表格保持一致
        order = {r: i for i, r in enumerate(Palette.ordered_ranks())}
        rows = sorted(self._detail_rows,
                      key=lambda x: order.get(x[1], 99), reverse=True)
        # 数据太多时全画会非常高,这里限制最多 60 行,避免图片过大
        limited = rows[:60]

        # 行高约 0.3 英寸,再留出表头与标题空间
        fig = Figure(figsize=(9, max(2, len(limited) * 0.3 + 1)), tight_layout=True)
        ax = fig.add_subplot(111)
        ax.axis('off')  # 不显示坐标轴,只放表格
        if limited:
            cell_text = [[str(c) for c in row] for row in limited]
            table = ax.table(cellText=cell_text, colLabels=headers,
                             cellLoc='center', loc='center')
            table.auto_set_font_size(False)
            table.set_fontsize(9)
            table.scale(1, 1.4)
            # 给"掌握度"列的文字上色,直观区分
            for r, row in enumerate(limited):
                cell = table[r + 1, 1]  # +1 跳过表头行
                cell.get_text().set_color(Palette.color_of(row[1]))
        title = '单词详情表'
        if len(rows) > len(limited):
            title += '(仅显示前 {} / 共 {} 条)'.format(len(limited), len(rows))
        ax.set_title(title)
        fig.savefig(path, dpi=150)
