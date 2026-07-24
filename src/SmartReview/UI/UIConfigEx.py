# -*- coding: utf-8 -*-
# @File    : UIConfigEx.py
# @说明    : 增强版复习词提取配置: 长度滑条/首字母多选/关联/笔记过滤 + 实时预览前50 + 预设保存/加载(JSON)
import os
import json
import logging
import math
from collections import defaultdict, Counter

from PyQt5.QtCore import Qt, pyqtSlot
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox, QLabel, QSlider,
    QLCDNumber, QRadioButton, QButtonGroup, QTableWidget, QTableWidgetItem,
    QListWidget, QListWidgetItem, QAbstractItemView, QComboBox, QPushButton,
    QLineEdit, QDialogButtonBox, QSplitter, QWidget, QMessageBox, QHeaderView,
    QCheckBox
)

from SmartReview.UI import UIConfig  # 复用原版字段命名习惯
from SmartReview.Base import basepath

logger = logging.getLogger(__name__)

PRESETS_PATH = os.path.join(basepath, 'presets.json')
LAST_CFG_PATH = os.path.join(basepath, 'last_config.json')


class ConfigDialogEx(QDialog):
    """ 增强版配置对话框,向下兼容原 ConfigDialog 的关键字段 """

    def __init__(self, book, parent=None):
        super().__init__(parent)
        self.book = book
        self.setWindowTitle('复习词提取(增强版)')
        self.resize(1100, 680)

        self._build_ui()
        self._connect_signals()
        self._load_presets()
        self._load_last_config()
        self._fill_primary_tables()
        self._refresh_preview()

    # ============================================================ UI 构建
    def _build_ui(self):
        root = QVBoxLayout(self)

        # 上半部分: 左侧条件 + 右侧预览
        splitter = QSplitter(Qt.Horizontal)

        # ----------- 左侧条件区 -----------
        left = QWidget()
        left_lay = QVBoxLayout(left)

        # 复习量
        count_box = QGroupBox('复习量')
        cl = QHBoxLayout(count_box)
        self.countLabel = QLabel('复习量:')
        self.countSlider = QSlider(Qt.Horizontal)
        self.countSlider.setMinimum(10); self.countSlider.setMaximum(300); self.countSlider.setValue(100)
        self.countLCD = QLCDNumber()
        self.countLCD.setDigitCount(4)
        cl.addWidget(self.countLabel); cl.addWidget(self.countSlider, 1); cl.addWidget(self.countLCD)
        left_lay.addWidget(count_box)

        # 两个表格(掌握度 + 截止时间) —— 字段名与旧版一致
        tables_lay = QHBoxLayout()
        ranks_box = QGroupBox('掌握程度')
        rl = QVBoxLayout(ranks_box)
        self.ranksTable = QTableWidget(0, 2)
        self.ranksTable.setHorizontalHeaderLabels(['程度', '数量'])
        self.ranksTable.setEditTriggers(QTableWidget.NoEditTriggers)
        self.ranksTable.setSelectionBehavior(QTableWidget.SelectRows)
        self.ranksTable.setSelectionMode(QAbstractItemView.MultiSelection)
        self.ranksTable.setSortingEnabled(True)
        rl.addWidget(self.ranksTable)
        tables_lay.addWidget(ranks_box)

        times_box = QGroupBox('截止时间')
        tl = QVBoxLayout(times_box)
        self.timesTable = QTableWidget(0, 2)
        self.timesTable.setHorizontalHeaderLabels(['时间', '数量'])
        self.timesTable.setEditTriggers(QTableWidget.NoEditTriggers)
        self.timesTable.setSelectionBehavior(QTableWidget.SelectRows)
        self.timesTable.setSelectionMode(QAbstractItemView.MultiSelection)
        self.timesTable.setSortingEnabled(True)
        tl.addWidget(self.timesTable)
        tables_lay.addWidget(times_box)
        left_lay.addLayout(tables_lay, 1)

        # 高级过滤: 长度/首字母/关联/笔记
        adv_box = QGroupBox('高级过滤')
        gl = QGridLayout(adv_box)

        gl.addWidget(QLabel('单词长度:'), 0, 0)
        self.lenMinSlider = QSlider(Qt.Horizontal)
        self.lenMinSlider.setMinimum(1); self.lenMinSlider.setMaximum(20); self.lenMinSlider.setValue(1)
        self.lenMaxSlider = QSlider(Qt.Horizontal)
        self.lenMaxSlider.setMinimum(1); self.lenMaxSlider.setMaximum(20); self.lenMaxSlider.setValue(20)
        self.lenMinLCD = QLCDNumber(); self.lenMinLCD.setDigitCount(2)
        self.lenMaxLCD = QLCDNumber(); self.lenMaxLCD.setDigitCount(2)
        gl.addWidget(self.lenMinSlider, 0, 1); gl.addWidget(self.lenMinLCD, 0, 2)
        gl.addWidget(self.lenMaxSlider, 0, 4); gl.addWidget(self.lenMaxLCD, 0, 5)
        gl.addWidget(QLabel('~'), 0, 3)

        # 首字母多选
        gl.addWidget(QLabel('首字母:'), 1, 0)
        self.initialList = QListWidget()
        self.initialList.setFlow(QListWidget.LeftToRight)
        self.initialList.setWrapping(True)
        self.initialList.setFixedHeight(56)
        self.initialList.setSelectionMode(QAbstractItemView.MultiSelection)
        for ch in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ':
            it = QListWidgetItem(ch)
            self.initialList.addItem(it)
        self.initialAllChk = QCheckBox('全选/清空')
        gl.addWidget(self.initialList, 1, 1, 1, 5)

        # 关联过滤
        gl.addWidget(QLabel('关联词:'), 2, 0)
        self.assocCombo = QComboBox()
        self.assocCombo.addItems(['不限', '仅有关联词', '仅无关联词'])
        gl.addWidget(self.assocCombo, 2, 1, 1, 2)
        self.selectAllAssocChk = QCheckBox('仅含关联的词')
        gl.addWidget(QLabel('笔记:'), 2, 3)
        self.notesCombo = QComboBox()
        self.notesCombo.addItems(['不限', '仅含笔记', '仅无笔记'])
        gl.addWidget(self.notesCombo, 2, 4, 1, 2)

        left_lay.addWidget(adv_box)

        # 提取方式
        extract_box = QGroupBox('提取方式')
        eh = QHBoxLayout(extract_box)
        self.radioPriority = QRadioButton('优先级')
        self.radioProportion = QRadioButton('比例均摊')
        self.radioProportion.setChecked(True)
        self.method_group = QButtonGroup(self)
        self.method_group.addButton(self.radioPriority)
        self.method_group.addButton(self.radioProportion)
        eh.addWidget(self.radioPriority); eh.addWidget(self.radioProportion)
        eh.addStretch(1)
        self.selectedLabel = QLabel('待背数量:')
        self.selectedLCD = QLCDNumber(); self.selectedLCD.setDigitCount(5)
        eh.addWidget(self.selectedLabel); eh.addWidget(self.selectedLCD)
        left_lay.addWidget(extract_box)

        splitter.addWidget(left)

        # ----------- 右侧预览区 -----------
        right = QWidget()
        rlay = QVBoxLayout(right)
        rlay.addWidget(QLabel('实时预览(符合条件的前 50 个单词):'))
        self.previewTable = QTableWidget(0, 4)
        self.previewTable.setHorizontalHeaderLabels(['单词', '掌握度', '下次复习', '释义'])
        self.previewTable.setEditTriggers(QTableWidget.NoEditTriggers)
        self.previewTable.setSelectionBehavior(QTableWidget.SelectRows)
        self.previewTable.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        rlay.addWidget(self.previewTable, 1)
        self.previewSummary = QLabel('共 0 个匹配')
        self.previewSummary.setStyleSheet('color:#7f8c8d;')
        rlay.addWidget(self.previewSummary)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        root.addWidget(splitter, 1)

        # ----------- 底部: 预设 + 确定/取消 -----------
        preset_bar = QHBoxLayout()
        preset_bar.addWidget(QLabel('预设:'))
        self.presetNameEdit = QLineEdit()
        self.presetNameEdit.setPlaceholderText('预设名(如: 快速复习)')
        self.presetNameEdit.setMaximumWidth(180)
        preset_bar.addWidget(self.presetNameEdit)
        self.btnSavePreset = QPushButton('保存预设')
        preset_bar.addWidget(self.btnSavePreset)
        self.presetCombo = QComboBox()
        self.presetCombo.setMinimumWidth(180)
        preset_bar.addWidget(self.presetCombo)
        self.btnLoadPreset = QPushButton('加载')
        preset_bar.addWidget(self.btnLoadPreset)
        self.btnDelPreset = QPushButton('删除')
        preset_bar.addWidget(self.btnDelPreset)
        preset_bar.addStretch(1)

        self.buttonBox = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        preset_bar.addWidget(self.buttonBox)
        root.addLayout(preset_bar)

        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)

    # ============================================================ 信号
    def _connect_signals(self):
        self.countSlider.valueChanged.connect(self.countLCD.display)
        self.lenMinSlider.valueChanged.connect(self.lenMinLCD.display)
        self.lenMaxSlider.valueChanged.connect(self.lenMaxLCD.display)
        # 任意条件变化都刷新预览
        for sig in [
            self.countSlider.valueChanged,
            self.lenMinSlider.valueChanged, self.lenMaxSlider.valueChanged,
            self.assocCombo.currentIndexChanged, self.notesCombo.currentIndexChanged,
        ]:
            sig.connect(self._refresh_preview)
        self.ranksTable.itemSelectionChanged.connect(self._refresh_preview)
        self.timesTable.itemSelectionChanged.connect(self._refresh_preview)
        self.initialList.itemSelectionChanged.connect(self._refresh_preview)
        self.radioPriority.toggled.connect(self._refresh_preview)

        self.initialAllChk.stateChanged.connect(self._toggle_initials)
        self.btnSavePreset.clicked.connect(self._save_preset)
        self.btnLoadPreset.clicked.connect(self._load_preset)
        self.btnDelPreset.clicked.connect(self._delete_preset)

    def _toggle_initials(self, state):
        check = state == Qt.Checked
        for i in range(self.initialList.count()):
            self.initialList.item(i).setSelected(check)

    # ============================================================ 主表填充
    def _fill_primary_tables(self):
        self._fill_table(self.ranksTable, self.book.info_ranks)
        self._fill_table(self.timesTable, self.book.info_times)
        # 默认勾选
        self._select_default(self.ranksTable, list(self.book.info_ranks.keys()))
        self._select_default(self.timesTable, list(self.book.info_times.keys())[:3])

    @staticmethod
    def _fill_table(table, source):
        table.setSortingEnabled(False)
        table.setRowCount(len(source))
        for i, (k, v) in enumerate(source.items()):
            table.setItem(i, 0, QTableWidgetItem(str(k)))
            table.setItem(i, 1, QTableWidgetItem(str(v)))
        table.resizeColumnsToContents()
        table.setSortingEnabled(True)

    @staticmethod
    def _select_default(table, keys):
        for i in range(table.rowCount()):
            item = table.item(i, 0)
            if item and item.text() in keys:
                table.selectRow(i)

    # ============================================================ 过滤条件
    def _current_filters(self):
        """ 收集当前界面的过滤条件,返回一个可 JSON 序列化的 dict """
        def _selected_col0(table):
            # selectedRows(0) 返回 QModelIndex 列表,直接取 data() 即可
            return [idx.data() for idx in table.selectionModel().selectedRows(0)]
        ranks = _selected_col0(self.ranksTable)
        times = _selected_col0(self.timesTable)
        initials = [it.text() for it in self.initialList.selectedItems()]
        return {
            'count': self.countSlider.value(),
            'ranks': ranks,
            'times': times,
            'len_min': self.lenMinSlider.value(),
            'len_max': self.lenMaxSlider.value(),
            'initials': initials,
            'assoc': self.assocCombo.currentIndex(),   # 0不限 1有 2无
            'notes': self.notesCombo.currentIndex(),   # 0不限 1有 2无
            'method': 'proportion' if self.radioProportion.isChecked() else 'priority',
        }

    def _apply_filters(self, filters):
        """ 根据条件从 book 中筛选候选单词 """
        ranks = set(filters['ranks'])
        times = set(filters['times'])
        initials = set(c.lower() for c in filters['initials'])
        lmin = filters['len_min']; lmax = filters['len_max']
        candidates = []
        for w in self.book.data.values():
            # 不在 reviewList 里(已是当前会话中单词)的才考虑
            if w in self.book.reviewList:
                continue
            if ranks and w.rank not in ranks:
                continue
            if times and w.review.next_review_time not in times:
                continue
            wlen = len(w.value)
            if wlen < lmin or wlen > lmax:
                continue
            if initials and (not w.value or w.value[0].lower() not in initials):
                continue
            has_assoc = len(w.associate) > 0
            if filters['assoc'] == 1 and not has_assoc:
                continue
            if filters['assoc'] == 2 and has_assoc:
                continue
            has_notes = bool((w.notes or '').strip())
            if filters['notes'] == 1 and not has_notes:
                continue
            if filters['notes'] == 2 and has_notes:
                continue
            candidates.append(w)
        # 排序: 按优先级
        candidates.sort(key=lambda x: x.priority)
        return candidates

    # ============================================================ 预览
    def _refresh_preview(self):
        # 保证 min<=max
        if self.lenMinSlider.value() > self.lenMaxSlider.value():
            self.lenMinSlider.setValue(self.lenMaxSlider.value())

        filters = self._current_filters()
        candidates = self._apply_filters(filters)
        self.selectedLCD.display(len(candidates))

        # 预览前 50
        self.previewTable.setSortingEnabled(False)
        preview = candidates[:50]
        self.previewTable.setRowCount(len(preview))
        for i, w in enumerate(preview):
            self.previewTable.setItem(i, 0, QTableWidgetItem(w.value))
            self.previewTable.setItem(i, 1, QTableWidgetItem(w.rank))
            self.previewTable.setItem(i, 2, QTableWidgetItem(w.review.next_review_time))
            self.previewTable.setItem(i, 3, QTableWidgetItem(w.explain.replace('\n', ' ')[:80]))
        self.previewTable.resizeColumnsToContents()
        self.previewTable.setSortingEnabled(True)
        self.previewSummary.setText('共 {} 个匹配单词, 预览前 50 个'.format(len(candidates)))

    # ============================================================ 确定: 真正选入 reviewList
    def accept(self):
        filters = self._current_filters()
        candidates = self._apply_filters(filters)
        count = filters['count']
        method = filters['method']
        if not candidates:
            QMessageBox.warning(self, '没有单词', '当前筛选条件下没有可复习单词,请调整筛选条件。')
            return

        # 清空旧的 reviewList(只清空未在背诵中的? 这里遵循旧逻辑: 用户重新配置意味着要重置)
        self.book.reviewList.clear()

        if method == 'proportion':
            # 按 rank 比例均摊
            bucket = defaultdict(list)
            for w in candidates:
                bucket[w.rank].append(w)
            total = len(candidates)
            allocated = 0
            for rank, lst in bucket.items():
                take = max(1, math.ceil(len(lst) / total * count))
                self.book.reviewList.extend(lst[:take])
                allocated += take
            # 若总数不足, 按优先级补齐
            if len(self.book.reviewList) < count:
                chosen = set(self.book.reviewList)
                for w in candidates:
                    if w not in chosen:
                        self.book.reviewList.append(w)
                        if len(self.book.reviewList) >= count:
                            break
            else:
                # 若超出, 截断
                del self.book.reviewList[count:]
        else:
            # 优先级: 已经按 priority 排序
            for w in candidates[:count]:
                self.book.reviewList.append(w)

        logger.info('增强配置选出 {} 个单词 (method={})'.format(len(self.book.reviewList), method))
        self._save_last_config(filters)
        super().accept()

    # ============================================================ 预设持久化(JSON)
    def _load_presets(self):
        self.presets = {}
        if os.path.isfile(PRESETS_PATH):
            try:
                with open(PRESETS_PATH, 'r', encoding='utf-8') as f:
                    self.presets = json.load(f)
            except Exception:
                logger.warning('presets.json 读取失败,已忽略')
                self.presets = {}
        self.presetCombo.clear()
        self.presetCombo.addItems(sorted(self.presets.keys()))

    def _save_preset(self):
        name = self.presetNameEdit.text().strip()
        if not name:
            QMessageBox.information(self, '提示', '请填写预设名称')
            return
        self.presets[name] = self._current_filters()
        self._persist_presets()
        self._load_presets()
        self.presetCombo.setCurrentText(name)
        QMessageBox.information(self, '已保存', '预设 "{}" 已保存'.format(name))

    def _load_preset(self):
        name = self.presetCombo.currentText()
        if not name or name not in self.presets:
            return
        self._apply_filters_to_ui(self.presets[name])

    def _delete_preset(self):
        name = self.presetCombo.currentText()
        if not name or name not in self.presets:
            return
        self.presets.pop(name, None)
        self._persist_presets()
        self._load_presets()

    def _persist_presets(self):
        try:
            os.makedirs(basepath, exist_ok=True)
            with open(PRESETS_PATH, 'w', encoding='utf-8') as f:
                json.dump(self.presets, f, ensure_ascii=False, indent=2)
        except Exception:
            logger.exception('保存预设失败')

    # ---- 上次配置持久化 ----
    def _load_last_config(self):
        if not os.path.isfile(LAST_CFG_PATH):
            return
        try:
            with open(LAST_CFG_PATH, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            self._apply_filters_to_ui(cfg)
        except Exception:
            logger.debug('读取 last_config 失败,忽略')

    def _save_last_config(self, filters):
        try:
            os.makedirs(basepath, exist_ok=True)
            with open(LAST_CFG_PATH, 'w', encoding='utf-8') as f:
                json.dump(filters, f, ensure_ascii=False, indent=2)
        except Exception:
            logger.debug('保存 last_config 失败,忽略')

    def _apply_filters_to_ui(self, f):
        """ 将 dict 应用到界面控件 """
        self.countSlider.setValue(f.get('count', 100))
        self.lenMinSlider.setValue(f.get('len_min', 1))
        self.lenMaxSlider.setValue(f.get('len_max', 20))
        self.assocCombo.setCurrentIndex(f.get('assoc', 0))
        self.notesCombo.setCurrentIndex(f.get('notes', 0))
        if f.get('method') == 'priority':
            self.radioPriority.setChecked(True)
        else:
            self.radioProportion.setChecked(True)
        # 首字母
        want = set(f.get('initials', []))
        for i in range(self.initialList.count()):
            it = self.initialList.item(i)
            it.setSelected(it.text() in want)
        # ranks/times 默认先全清再选,避免在表还没填充时崩溃
        self._select_keys(self.ranksTable, set(f.get('ranks', [])))
        self._select_keys(self.timesTable, set(f.get('times', [])))
        self._refresh_preview()

    @staticmethod
    def _select_keys(table, keys):
        table.clearSelection()
        for i in range(table.rowCount()):
            it = table.item(i, 0)
            if it and it.text() in keys:
                table.selectRow(i)
