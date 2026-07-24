# -*- coding: utf-8 -*-
# @File    : ConfigPanel.py
# @Desc    : 增强版"复习词提取"配置界面。
#
# 需求 3:在现有(掌握度 / 截止时间 / 复习量 / 提取方式)维度上,新增:
#   - 单词长度滑条(按字母数范围过滤);
#   - 首字母多选(A~Z / 其他);
#   - 关联过滤(全部 / 仅有关联词 / 仅无关联词);
#   - 笔记(释义)过滤(全部 / 有释义 / 无释义)。
#   右侧新增"实时预览前 50 个单词"列表,随任意条件变动即时刷新。
#   底部支持"预设保存 / 加载"(如"快速复习"预设),数据序列化为 JSON 持久化。
#
# 兼容性:仍然对外暴露 self.book,并在 accept() 时把筛选结果灌入 book.reviewList,
#         与旧的 MainWindow 调用方式保持一致。
import os
import json
import string
import logging

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox, QLabel,
    QSlider, QLCDNumber, QTableWidget, QTableWidgetItem, QListWidget,
    QListWidgetItem, QComboBox, QPushButton, QRadioButton, QDialogButtonBox,
    QMessageBox, QInputDialog, QWidget, QAbstractItemView,
)

from SmartReview.Tactics import LearnTactics
from SmartReview.Base import Vocabulary
from SmartReview.Base import basepath

# 预设持久化文件(与词库数据库同目录)
PRESET_PATH = os.path.join(basepath, 'config_presets.json')

PREVIEW_LIMIT = 50  # 右侧预览最多显示的单词数

logger = logging.getLogger(__name__)


class ConfigPanel(QDialog):
    """ 增强版复习配置对话框 """

    def __init__(self, *args, **kwargs):
        super(ConfigPanel, self).__init__(*args, **kwargs)
        self.setWindowTitle('复习词提取 · 增强配置')
        self.resize(860, 620)
        self.book = LearnTactics.loadFrom()  # 加载单词书(与旧实现一致)

        # 用一个防抖定时器,避免拖动滑条时预览刷新过于频繁
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(120)
        self._debounce.timeout.connect(self._refresh_preview)

        self._build_ui()
        self._init_values()
        self._connect_signals()
        self._refresh_preview()

    # ------------------------------------------------------------------
    #  UI 构建
    # ------------------------------------------------------------------
    def _build_ui(self):
        root = QVBoxLayout(self)
        body = QHBoxLayout()
        root.addLayout(body)

        # ---------- 左列:掌握度 / 截止时间 ----------
        left = QVBoxLayout()
        left.addWidget(QLabel('掌握程度:'))
        self.ranksTable = self._make_multiselect_table()
        left.addWidget(self.ranksTable)
        left.addWidget(QLabel('截止时间:'))
        self.timesTable = self._make_multiselect_table()
        left.addWidget(self.timesTable)
        body.addLayout(left, 2)

        # ---------- 中列:新增过滤维度 ----------
        mid = QVBoxLayout()

        # 单词长度滑条(双滑条:最小 / 最大)
        lenBox = QGroupBox('单词长度过滤')
        lenLayout = QGridLayout(lenBox)
        self.minLenSlider = QSlider(Qt.Horizontal)
        self.maxLenSlider = QSlider(Qt.Horizontal)
        self.minLenLabel = QLabel()
        self.maxLenLabel = QLabel()
        lenLayout.addWidget(QLabel('最短:'), 0, 0)
        lenLayout.addWidget(self.minLenSlider, 0, 1)
        lenLayout.addWidget(self.minLenLabel, 0, 2)
        lenLayout.addWidget(QLabel('最长:'), 1, 0)
        lenLayout.addWidget(self.maxLenSlider, 1, 1)
        lenLayout.addWidget(self.maxLenLabel, 1, 2)
        mid.addWidget(lenBox)

        # 首字母多选
        letterBox = QGroupBox('首字母(不选=全部)')
        letterLayout = QVBoxLayout(letterBox)
        self.letterList = QListWidget()
        self.letterList.setSelectionMode(QAbstractItemView.MultiSelection)
        self.letterList.setFlow(QListWidget.LeftToRight)
        self.letterList.setWrapping(True)
        self.letterList.setFixedHeight(110)
        for ch in string.ascii_uppercase:
            self.letterList.addItem(QListWidgetItem(ch))
        self.letterList.addItem(QListWidgetItem('#'))  # 非字母开头
        letterLayout.addWidget(self.letterList)
        mid.addWidget(letterBox)

        # 关联 / 笔记过滤
        filterBox = QGroupBox('关联 / 笔记过滤')
        fLayout = QGridLayout(filterBox)
        self.assocCombo = QComboBox()
        self.assocCombo.addItems(['全部', '仅有关联词', '仅无关联词'])
        self.noteCombo = QComboBox()
        self.noteCombo.addItems(['全部', '有释义', '无释义'])
        fLayout.addWidget(QLabel('关联词:'), 0, 0)
        fLayout.addWidget(self.assocCombo, 0, 1)
        fLayout.addWidget(QLabel('释义:'), 1, 0)
        fLayout.addWidget(self.noteCombo, 1, 1)
        mid.addWidget(filterBox)

        # 复习量 + 提取方式
        countBox = QGroupBox('复习量 & 提取方式')
        cLayout = QGridLayout(countBox)
        self.countSlider = QSlider(Qt.Horizontal)
        self.countLCD = QLCDNumber()
        cLayout.addWidget(QLabel('复习量:'), 0, 0)
        cLayout.addWidget(self.countSlider, 0, 1)
        cLayout.addWidget(self.countLCD, 0, 2)
        self.radioPriority = QRadioButton('优先级')
        self.radioProportion = QRadioButton('比例均摊')
        self.radioProportion.setChecked(True)
        cLayout.addWidget(self.radioPriority, 1, 0)
        cLayout.addWidget(self.radioProportion, 1, 1)
        mid.addWidget(countBox)
        mid.addStretch()
        body.addLayout(mid, 2)

        # ---------- 右列:实时预览 ----------
        right = QVBoxLayout()
        self.previewTitle = QLabel('实时预览(前 {} 个):'.format(PREVIEW_LIMIT))
        right.addWidget(self.previewTitle)
        self.previewList = QListWidget()
        right.addWidget(self.previewList)
        self.matchLabel = QLabel('匹配: 0')
        right.addWidget(self.matchLabel)
        body.addLayout(right, 3)

        # ---------- 底部:预设 + 确定 / 取消 ----------
        bottom = QHBoxLayout()
        bottom.addWidget(QLabel('预设:'))
        self.presetCombo = QComboBox()
        bottom.addWidget(self.presetCombo)
        self.loadPresetBtn = QPushButton('加载')
        self.savePresetBtn = QPushButton('保存为…')
        self.delPresetBtn = QPushButton('删除')
        bottom.addWidget(self.loadPresetBtn)
        bottom.addWidget(self.savePresetBtn)
        bottom.addWidget(self.delPresetBtn)
        bottom.addStretch()
        self.buttonBox = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bottom.addWidget(self.buttonBox)
        root.addLayout(bottom)

    @staticmethod
    def _make_multiselect_table():
        """ 生成一个两列、可多选的表格 """
        table = QTableWidget()
        table.setColumnCount(2)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.MultiSelection)
        return table

    # ------------------------------------------------------------------
    #  初始值
    # ------------------------------------------------------------------
    def _init_values(self):
        # 掌握度 / 时间 表格填充
        self._fill_table(self.ranksTable, ['程度', '数量'], self.book.info_ranks,
                         Vocabulary.default_ranks_chooses())
        self._fill_table(self.timesTable, ['时间', '数量'], self.book.info_times,
                         Vocabulary.default_times_chooses())

        # 长度滑条:依据词库真实最短/最长单词设定范围
        lengths = [len(w) for w in self.book.data] or [1]
        lo, hi = min(lengths), max(lengths)
        for s in (self.minLenSlider, self.maxLenSlider):
            s.setMinimum(lo)
            s.setMaximum(hi)
        self.minLenSlider.setValue(lo)
        self.maxLenSlider.setValue(hi)
        self.minLenLabel.setText(str(lo))
        self.maxLenLabel.setText(str(hi))

        # 复习量滑条
        self.countSlider.setMinimum(10)
        self.countSlider.setMaximum(120)
        self.countSlider.setValue(100)
        self.countLCD.display(100)

        # 载入预设下拉
        self._reload_preset_combo()

    def _fill_table(self, table, headers, source, default_chooses):
        table.setHorizontalHeaderLabels(headers)
        table.setRowCount(len(source))
        for index, (key, value) in enumerate(source.items()):
            table.setItem(index, 0, QTableWidgetItem(str(key)))
            table.setItem(index, 1, QTableWidgetItem(str(value)))
            if key in default_chooses:
                table.selectRow(index)
        table.resizeColumnsToContents()

    # ------------------------------------------------------------------
    #  信号
    # ------------------------------------------------------------------
    def _connect_signals(self):
        # 复习量 slider 联动 LCD
        self.countSlider.valueChanged.connect(self.countLCD.display)
        # 长度滑条:更新数值标签 + 保证 min<=max + 触发预览
        self.minLenSlider.valueChanged.connect(self._on_len_changed)
        self.maxLenSlider.valueChanged.connect(self._on_len_changed)
        # 任意过滤条件变化都触发预览(防抖)
        self.ranksTable.itemSelectionChanged.connect(self._schedule_refresh)
        self.timesTable.itemSelectionChanged.connect(self._schedule_refresh)
        self.letterList.itemSelectionChanged.connect(self._schedule_refresh)
        self.assocCombo.currentIndexChanged.connect(self._schedule_refresh)
        self.noteCombo.currentIndexChanged.connect(self._schedule_refresh)
        # 预设按钮
        self.loadPresetBtn.clicked.connect(self._load_selected_preset)
        self.savePresetBtn.clicked.connect(self._save_preset)
        self.delPresetBtn.clicked.connect(self._delete_preset)
        # 确定 / 取消
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)

    def _on_len_changed(self):
        # 防止最小值超过最大值
        if self.minLenSlider.value() > self.maxLenSlider.value():
            sender = self.sender()
            if sender is self.minLenSlider:
                self.maxLenSlider.setValue(self.minLenSlider.value())
            else:
                self.minLenSlider.setValue(self.maxLenSlider.value())
        self.minLenLabel.setText(str(self.minLenSlider.value()))
        self.maxLenLabel.setText(str(self.maxLenSlider.value()))
        self._schedule_refresh()

    def _schedule_refresh(self):
        """ 触发防抖刷新 """
        self._debounce.start()

    # ------------------------------------------------------------------
    #  过滤 & 预览
    # ------------------------------------------------------------------
    @staticmethod
    def _selected_keys(table):
        return [i.data() for i in table.selectedIndexes() if i.column() == 0]

    def _current_filters(self):
        """ 汇总当前界面上的全部过滤条件 """
        return {
            'ranks': self._selected_keys(self.ranksTable),
            'times': self._selected_keys(self.timesTable),
            'min_len': self.minLenSlider.value(),
            'max_len': self.maxLenSlider.value(),
            'letters': [i.text() for i in self.letterList.selectedItems()],
            'assoc': self.assocCombo.currentIndex(),   # 0 全部 / 1 有 / 2 无
            'note': self.noteCombo.currentIndex(),      # 0 全部 / 1 有 / 2 无
            'count': self.countSlider.value(),
            'method': 'priority' if self.radioPriority.isChecked() else 'proportion',
        }

    def _match_words(self, filters):
        """ 依据过滤条件返回匹配的 Vocabulary 列表(未截断) """
        ranks = filters['ranks'] or None
        times = filters['times'] or None
        letters = set(filters['letters'])
        result = []
        for word_obj in self.book.data.values():
            word = word_obj.value
            # 掌握度 / 时间(复用原有 is_need_review 语义)
            if not word_obj.is_need_review(ranks, times):
                continue
            # 长度
            if not (filters['min_len'] <= len(word) <= filters['max_len']):
                continue
            # 首字母
            if letters:
                first = word[0].upper() if word else '#'
                key = first if first in string.ascii_uppercase else '#'
                if key not in letters:
                    continue
            # 关联过滤
            if filters['assoc'] == 1 and not word_obj.associate:
                continue
            if filters['assoc'] == 2 and word_obj.associate:
                continue
            # 释义过滤
            has_note = bool(str(word_obj.explain).strip())
            if filters['note'] == 1 and not has_note:
                continue
            if filters['note'] == 2 and has_note:
                continue
            result.append(word_obj)
        # 按优先级排序,让最需要复习的排在前面
        result.sort(key=lambda x: x.priority)
        return result

    def _refresh_preview(self):
        """ 刷新右侧预览列表 """
        filters = self._current_filters()
        matched = self._match_words(filters)
        self.previewList.clear()
        for word_obj in matched[:PREVIEW_LIMIT]:
            self.previewList.addItem('{}  ·  {}'.format(word_obj.value, word_obj.rank))
        self.matchLabel.setText('匹配: {}  (将提取 {} 个)'
                                .format(len(matched), min(len(matched), filters['count'])))

    # ------------------------------------------------------------------
    #  预设持久化(JSON)
    # ------------------------------------------------------------------
    def _load_presets_file(self):
        if os.path.isfile(PRESET_PATH):
            try:
                with open(PRESET_PATH, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (OSError, ValueError):
                return {}
        return {}

    def _write_presets_file(self, presets):
        os.makedirs(os.path.dirname(PRESET_PATH), exist_ok=True)
        with open(PRESET_PATH, 'w', encoding='utf-8') as f:
            json.dump(presets, f, ensure_ascii=False, indent=2)

    def _reload_preset_combo(self):
        presets = self._load_presets_file()
        # 若没有任何预设,内置一个"快速复习"示例预设
        if not presets:
            presets = {
                '快速复习': {
                    'ranks': ['忘记', '顽固', '混淆'], 'times': [],
                    'min_len': self.minLenSlider.minimum(),
                    'max_len': self.maxLenSlider.maximum(),
                    'letters': [], 'assoc': 0, 'note': 0,
                    'count': 30, 'method': 'priority',
                }
            }
            self._write_presets_file(presets)
        self.presetCombo.clear()
        self.presetCombo.addItems(sorted(presets.keys()))

    def _apply_filters(self, filters):
        """ 把一组过滤条件回填到界面控件上 """
        # 掌握度 / 时间
        self._select_rows_by_keys(self.ranksTable, filters.get('ranks', []))
        self._select_rows_by_keys(self.timesTable, filters.get('times', []))
        # 长度
        self.minLenSlider.setValue(filters.get('min_len', self.minLenSlider.minimum()))
        self.maxLenSlider.setValue(filters.get('max_len', self.maxLenSlider.maximum()))
        # 首字母
        wanted = set(filters.get('letters', []))
        for i in range(self.letterList.count()):
            item = self.letterList.item(i)
            item.setSelected(item.text() in wanted)
        # 关联 / 释义
        self.assocCombo.setCurrentIndex(filters.get('assoc', 0))
        self.noteCombo.setCurrentIndex(filters.get('note', 0))
        # 复习量 / 方式
        self.countSlider.setValue(filters.get('count', 100))
        if filters.get('method') == 'priority':
            self.radioPriority.setChecked(True)
        else:
            self.radioProportion.setChecked(True)
        self._refresh_preview()

    @staticmethod
    def _select_rows_by_keys(table, keys):
        table.clearSelection()
        keys = set(keys)
        for row in range(table.rowCount()):
            item = table.item(row, 0)
            if item and item.text() in keys:
                table.selectRow(row)

    def _load_selected_preset(self):
        name = self.presetCombo.currentText()
        if not name:
            return
        presets = self._load_presets_file()
        if name in presets:
            self._apply_filters(presets[name])

    def _save_preset(self):
        name, ok = QInputDialog.getText(self, '保存预设', '预设名称:')
        if not ok or not name.strip():
            return
        presets = self._load_presets_file()
        presets[name.strip()] = self._current_filters()
        self._write_presets_file(presets)
        self._reload_preset_combo()
        self.presetCombo.setCurrentText(name.strip())
        QMessageBox.information(self, '已保存', '预设「{}」已保存。'.format(name.strip()))

    def _delete_preset(self):
        name = self.presetCombo.currentText()
        if not name:
            return
        presets = self._load_presets_file()
        if name in presets:
            del presets[name]
            self._write_presets_file(presets)
            self._reload_preset_combo()

    # ------------------------------------------------------------------
    #  确定:把筛选结果灌入待背队列
    # ------------------------------------------------------------------
    def accept(self):
        filters = self._current_filters()
        matched = self._match_words(filters)
        count = filters['count']

        # 边界处理 1:清理"旧数据"。
        # reviewList 里可能残留上一次配置留下、但本次已不符合筛选条件的单词,
        # 这里重建一个只保留"仍匹配"的新队列,避免旧词混入本次复习。
        matched_set = set(id(w) for w in matched)
        stale = [w for w in self.book.reviewList if id(w) not in matched_set]
        for w in stale:
            self.book.reviewList.remove(w)  # 移除不再匹配的旧词

        # 边界处理 2:去重来源。
        # 一个单词若已经在待背队列 reviewList,或已在本轮"记住/模糊/忘记"的
        # 进行中状态集里(masterySet / vagueSet / forgetList),都不应重复加入,
        # 否则同一个词会被背两次、或与进行中的状态冲突。
        existing = set()
        existing.update(id(w) for w in self.book.reviewList)
        for bucket in (self.book.masterySet, self.book.vagueSet, self.book.forgetList):
            existing.update(id(w) for w in bucket)

        # 按优先级顺序补足到目标数量(count 是"总的待背上限",已在队列中的也计入)
        added = 0
        current_total = len(self.book.reviewList)
        for word_obj in matched:
            if current_total + added >= count:  # 已达到目标复习量则停止
                break
            if id(word_obj) in existing:  # 去重:跳过已存在或进行中的词
                continue
            self.book.reviewList.append(word_obj)
            existing.add(id(word_obj))  # 同步登记,防止 matched 内部潜在重复
            added += 1

        logger.info('config accept: 清理旧词 %d, 新增 %d, 当前待背 %d',
                    len(stale), added, len(self.book.reviewList))
        super(ConfigPanel, self).accept()
