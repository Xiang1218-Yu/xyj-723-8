# -*- coding: utf-8 -*-
# @File    : ConfigEnhanced.py
# @Description: 增强配置界面 - 长度滑条、首字母多选、关联/笔记过滤、实时预览、预设管理
import os
import json
import logging
from collections import Counter

from PyQt5.QtCore import Qt, pyqtSlot
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox, QLabel,
    QSlider, QLCDNumber, QTableWidget, QTableWidgetItem, QHeaderView,
    QRadioButton, QButtonGroup, QPushButton, QListWidget, QListWidgetItem,
    QLineEdit, QSplitter, QWidget, QComboBox, QCheckBox, QMessageBox,
    QFileDialog, QInputDialog, QTabWidget, QAbstractItemView,
    QScrollArea, QFrame
)

from SmartReview.Base import Vocabulary

logger = logging.getLogger(__name__)

# 预设文件保存路径
from SmartReview.Base import basepath
PRESET_PATH = os.path.join(basepath, 'presets.json')


class ConfigEnhancedDialog(QDialog):
    """增强配置对话框 - 支持更多筛选维度和预设管理"""

    def __init__(self, book, parent=None):
        super().__init__(parent)
        self.book = book
        self.setWindowTitle('复习配置（增强版）')
        self.resize(1100, 780)
        self.presets = self._load_presets()
        self._setup_ui()
        self._connect_signals()
        self._refresh_preview()

    def _setup_ui(self):
        """构建UI布局"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # 使用QSplitter分割左侧配置区和右侧预览区
        splitter = QSplitter(Qt.Horizontal)

        # ===== 左侧：配置区 =====
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 5, 0)

        # --- 原有维度：掌握度 + 时间 ---
        dim_group = QGroupBox('筛选维度')
        dim_layout = QHBoxLayout(dim_group)

        # 掌握度选择
        ranks_layout = QVBoxLayout()
        ranks_layout.addWidget(QLabel('掌握程度:'))
        self.ranks_list = QListWidget()
        self.ranks_list.setSelectionMode(QAbstractItemView.MultiSelection)
        for rank in Vocabulary.rank_table:
            item = QListWidgetItem(rank)
            self.ranks_list.addItem(item)
            if rank in Vocabulary.default_ranks_chooses():
                item.setSelected(True)
        self.ranks_list.setMaximumHeight(180)
        ranks_layout.addWidget(self.ranks_list)
        dim_layout.addLayout(ranks_layout)

        # 时间选择
        times_layout = QVBoxLayout()
        times_layout.addWidget(QLabel('截止时间:'))
        self.times_list = QListWidget()
        self.times_list.setSelectionMode(QAbstractItemView.MultiSelection)
        for time_label in ['已逾期', '今早', '今晚', '明早', '明晚', '后天',
                           '第4天', '第7天', '第15天', '半个月后']:
            item = QListWidgetItem(time_label)
            self.times_list.addItem(item)
        # 默认选择
        from SmartReview.Base import ReviewManage
        for t in ReviewManage.default_times_chooses():
            for i in range(self.times_list.count()):
                if self.times_list.item(i).text() == t:
                    self.times_list.item(i).setSelected(True)
        self.times_list.setMaximumHeight(180)
        times_layout.addWidget(self.times_list)
        dim_layout.addLayout(times_layout)
        left_layout.addWidget(dim_group)

        # --- 新增维度：长度滑条 + 首字母多选 + 过滤选项 ---
        new_dim_group = QGroupBox('新增筛选维度')
        new_dim_layout = QGridLayout(new_dim_group)

        # 单词长度范围 - 使用双滑条实现
        new_dim_layout.addWidget(QLabel('单词长度范围:'), 0, 0)
        len_slider_layout = QVBoxLayout()

        # 最短长度滑条
        len_min_layout = QHBoxLayout()
        len_min_layout.addWidget(QLabel('最短:'))
        self.len_min_slider = QSlider(Qt.Horizontal)
        self.len_min_slider.setRange(1, 30)
        self.len_min_slider.setValue(1)
        self.len_min_slider.setTickPosition(QSlider.TicksBelow)
        self.len_min_slider.setTickInterval(5)
        len_min_layout.addWidget(self.len_min_slider)
        self.len_min_lcd = QLCDNumber()
        self.len_min_lcd.setDigitCount(2)
        self.len_min_lcd.setFixedWidth(45)
        self.len_min_lcd.display(1)
        len_min_layout.addWidget(self.len_min_lcd)
        len_slider_layout.addLayout(len_min_layout)

        # 最长长度滑条
        len_max_layout = QHBoxLayout()
        len_max_layout.addWidget(QLabel('最长:'))
        self.len_max_slider = QSlider(Qt.Horizontal)
        self.len_max_slider.setRange(1, 30)
        self.len_max_slider.setValue(20)
        self.len_max_slider.setTickPosition(QSlider.TicksBelow)
        self.len_max_slider.setTickInterval(5)
        len_max_layout.addWidget(self.len_max_slider)
        self.len_max_lcd = QLCDNumber()
        self.len_max_lcd.setDigitCount(2)
        self.len_max_lcd.setFixedWidth(45)
        self.len_max_lcd.display(20)
        len_max_layout.addWidget(self.len_max_lcd)
        len_slider_layout.addLayout(len_max_layout)

        new_dim_layout.addLayout(len_slider_layout, 0, 1)

        # 首字母多选
        new_dim_layout.addWidget(QLabel('首字母筛选:'), 1, 0)
        letter_layout = QHBoxLayout()
        self.letter_checks = {}
        letter_all_btn = QPushButton('全选')
        letter_all_btn.setFixedWidth(50)
        letter_all_btn.clicked.connect(lambda: self._set_all_letters(True))
        letter_layout.addWidget(letter_all_btn)
        letter_none_btn = QPushButton('清空')
        letter_none_btn.setFixedWidth(50)
        letter_none_btn.clicked.connect(lambda: self._set_all_letters(False))
        letter_layout.addWidget(letter_none_btn)
        letter_scroll = QScrollArea()
        letter_scroll.setWidgetResizable(True)
        letter_scroll.setFixedHeight(45)
        letter_container = QWidget()
        letter_grid = QHBoxLayout(letter_container)
        letter_grid.setContentsMargins(2, 2, 2, 2)
        for letter in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ':
            cb = QCheckBox(letter)
            cb.setChecked(True)
            cb.stateChanged.connect(self._refresh_preview)
            self.letter_checks[letter] = cb
            letter_grid.addWidget(cb)
        letter_grid.addStretch()
        letter_scroll.setWidget(letter_container)
        letter_layout.addWidget(letter_scroll, 1)
        new_dim_layout.addLayout(letter_layout, 1, 1)

        # 关联过滤
        new_dim_layout.addWidget(QLabel('关联状态:'), 2, 0)
        assoc_layout = QHBoxLayout()
        self.assoc_combo = QComboBox()
        self.assoc_combo.addItems(['全部', '有关联词', '无关联词'])
        assoc_layout.addWidget(self.assoc_combo)
        assoc_layout.addStretch()
        new_dim_layout.addLayout(assoc_layout, 2, 1)

        # 笔记过滤（独立实现，基于Vocabulary.notes字段）
        new_dim_layout.addWidget(QLabel('笔记状态:'), 3, 0)
        notes_layout = QHBoxLayout()
        self.notes_combo = QComboBox()
        self.notes_combo.addItems(['全部', '有笔记', '无笔记'])
        notes_layout.addWidget(self.notes_combo)
        notes_layout.addStretch()
        new_dim_layout.addLayout(notes_layout, 3, 1)

        left_layout.addWidget(new_dim_group)

        # --- 复习量设置 ---
        count_group = QGroupBox('复习设置')
        count_layout = QVBoxLayout(count_group)

        # 复习数量
        cnt_layout = QHBoxLayout()
        cnt_layout.addWidget(QLabel('复习量:'))
        self.countSlider = QSlider(Qt.Horizontal)
        self.countSlider.setMinimum(10)
        self.countSlider.setMaximum(200)
        self.countSlider.setValue(100)
        cnt_layout.addWidget(self.countSlider)
        self.countLCD = QLCDNumber()
        self.countLCD.setDigitCount(3)
        self.countLCD.display(100)
        cnt_layout.addWidget(self.countLCD)
        count_layout.addLayout(cnt_layout)

        # 提取方式
        extract_layout = QHBoxLayout()
        extract_layout.addWidget(QLabel('提取方式:'))
        self.radioProportion = QRadioButton('比例均摊')
        self.radioProportion.setChecked(True)
        self.radioPriority = QRadioButton('优先级')
        extract_layout.addWidget(self.radioProportion)
        extract_layout.addWidget(self.radioPriority)
        extract_layout.addStretch()
        count_layout.addLayout(extract_layout)

        # 统计信息
        self.selectedLCD = QLCDNumber()
        self.selectedLCD.setDigitCount(5)
        info_layout = QHBoxLayout()
        info_layout.addWidget(QLabel('符合条件的单词数:'))
        info_layout.addWidget(self.selectedLCD)
        info_layout.addStretch()
        count_layout.addLayout(info_layout)

        left_layout.addWidget(count_group)

        # --- 预设管理 ---
        preset_group = QGroupBox('预设管理')
        preset_layout = QHBoxLayout(preset_group)
        self.preset_combo = QComboBox()
        self._refresh_preset_combo()
        preset_layout.addWidget(QLabel('预设:'))
        preset_layout.addWidget(self.preset_combo)
        btn_save_preset = QPushButton('保存当前')
        btn_save_preset.clicked.connect(self._save_preset)
        preset_layout.addWidget(btn_save_preset)
        btn_load_preset = QPushButton('加载')
        btn_load_preset.clicked.connect(self._load_preset)
        preset_layout.addWidget(btn_load_preset)
        btn_del_preset = QPushButton('删除')
        btn_del_preset.clicked.connect(self._delete_preset)
        preset_layout.addWidget(btn_del_preset)
        left_layout.addWidget(preset_group)

        left_layout.addStretch()

        # 确认/取消按钮
        btn_layout = QHBoxLayout()
        btn_ok = QPushButton('开始复习')
        btn_ok.clicked.connect(self.accept)
        btn_cancel = QPushButton('取消')
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_ok)
        btn_layout.addWidget(btn_cancel)
        left_layout.addLayout(btn_layout)

        splitter.addWidget(left_widget)

        # ===== 右侧：实时预览区 =====
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(5, 0, 0, 0)

        right_layout.addWidget(QLabel('📋 实时预览（前50个符合条件的单词）'))
        self.preview_table = QTableWidget()
        self.preview_table.setColumnCount(6)
        self.preview_table.setHorizontalHeaderLabels(
            ['单词', '释义', '掌握度', '长度', '关联数', '笔记']
        )
        self.preview_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.preview_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.preview_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.preview_table.setAlternatingRowColors(True)
        right_layout.addWidget(self.preview_table)

        self.preview_count_label = QLabel('预览显示: 0 / 0')
        self.preview_count_label.setAlignment(Qt.AlignRight)
        self.preview_count_label.setStyleSheet('color: gray;')
        right_layout.addWidget(self.preview_count_label)

        splitter.addWidget(right_widget)
        splitter.setSizes([550, 550])
        main_layout.addWidget(splitter)

    def _connect_signals(self):
        """连接信号槽"""
        # 复习量滑条
        self.countSlider.valueChanged.connect(self.countLCD.display)
        # 长度滑条联动LCD
        self.len_min_slider.valueChanged.connect(self.len_min_lcd.display)
        self.len_max_slider.valueChanged.connect(self.len_max_lcd.display)
        # 长度滑条互斥约束：最短<=最长
        self.len_min_slider.valueChanged.connect(self._on_len_min_changed)
        self.len_max_slider.valueChanged.connect(self._on_len_max_changed)
        # 所有筛选条件变化时刷新预览
        self.ranks_list.itemSelectionChanged.connect(self._refresh_preview)
        self.times_list.itemSelectionChanged.connect(self._refresh_preview)
        self.len_min_slider.valueChanged.connect(self._refresh_preview)
        self.len_max_slider.valueChanged.connect(self._refresh_preview)
        self.assoc_combo.currentTextChanged.connect(self._refresh_preview)
        self.notes_combo.currentTextChanged.connect(self._refresh_preview)

    def _on_len_min_changed(self, value):
        """最短长度变化时，确保不超过最长"""
        if value > self.len_max_slider.value():
            self.len_max_slider.setValue(value)

    def _on_len_max_changed(self, value):
        """最长长度变化时，确保不短于最短"""
        if value < self.len_min_slider.value():
            self.len_min_slider.setValue(value)

    def _set_all_letters(self, checked):
        """全选/清空首字母"""
        for cb in self.letter_checks.values():
            cb.setChecked(checked)

    def _get_selected_letters(self):
        """获取选中的首字母集合"""
        return [letter for letter, cb in self.letter_checks.items() if cb.isChecked()]

    def _get_selected_ranks(self):
        """获取选中的掌握度列表"""
        return [item.text() for item in self.ranks_list.selectedItems()]

    def _get_selected_times(self):
        """获取选中的时间列表"""
        return [item.text() for item in self.times_list.selectedItems()]

    def _get_filtered_words(self):
        """根据当前筛选条件获取匹配的单词列表（按优先级排序）"""
        ranks = self._get_selected_ranks()
        times = self._get_selected_times()
        selected_letters = set(self._get_selected_letters())
        len_min = self.len_min_slider.value()
        len_max = self.len_max_slider.value()
        assoc_filter = self.assoc_combo.currentText()
        notes_filter = self.notes_combo.currentText()

        filtered = []
        for word in sorted(self.book.values(), key=lambda w: w.priority):
            # 掌握度筛选
            if ranks and word.rank not in ranks:
                continue
            # 时间筛选
            if times and not word.review.is_need_review(times):
                continue
            # 长度筛选
            wlen = len(word.value)
            if wlen < len_min or wlen > len_max:
                continue
            # 首字母筛选
            if word.value and word.value[0].upper() not in selected_letters:
                continue
            # 关联筛选
            if assoc_filter == '有关联词' and len(word.associate) == 0:
                continue
            if assoc_filter == '无关联词' and len(word.associate) > 0:
                continue
            # 笔记筛选（基于真实notes字段）
            has_notes = bool(word.notes and word.notes.strip())
            if notes_filter == '有笔记' and not has_notes:
                continue
            if notes_filter == '无笔记' and has_notes:
                continue
            filtered.append(word)

        return filtered

    def _refresh_preview(self):
        """刷新预览表格"""
        filtered_words = self._get_filtered_words()
        total_count = len(filtered_words)

        # 更新LCD
        self.selectedLCD.display(total_count)

        # 预览前50个
        preview_words = filtered_words[:50]
        self.preview_table.setRowCount(len(preview_words))

        for row, word in enumerate(preview_words):
            self.preview_table.setItem(row, 0, QTableWidgetItem(word.value))
            # 释义截断
            explain_short = word.explain[:50] + '...' if len(word.explain) > 50 else word.explain
            explain_short = explain_short.replace('\n', ' ')
            self.preview_table.setItem(row, 1, QTableWidgetItem(explain_short))
            self.preview_table.setItem(row, 2, QTableWidgetItem(word.rank))
            self.preview_table.setItem(row, 3, QTableWidgetItem(str(len(word.value))))
            self.preview_table.setItem(row, 4, QTableWidgetItem(str(len(word.associate))))
            # 笔记状态显示
            note_status = '📝' if (word.notes and word.notes.strip()) else '-'
            note_tip = word.notes[:30] + '...' if (word.notes and len(word.notes) > 30) else (word.notes or '')
            note_item = QTableWidgetItem(note_status)
            if note_tip:
                note_item.setToolTip(note_tip)
            self.preview_table.setItem(row, 5, note_item)

        self.preview_count_label.setText(
            '预览显示: {} / {} (前50个)'.format(len(preview_words), total_count)
        )

    def _load_presets(self):
        """从文件加载预设"""
        if os.path.exists(PRESET_PATH):
            try:
                with open(PRESET_PATH, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning('加载预设失败: {}'.format(e))
        # 默认预设
        return {
            '快速复习': {
                'ranks': ['忘记', '顽固', '混淆', '模糊'],
                'times': ['已逾期', '今早', '今晚'],
                'len_min': 1, 'len_max': 20,
                'letters': list('ABCDEFGHIJKLMNOPQRSTUVWXYZ'),
                'assoc_filter': '全部', 'notes_filter': '全部',
                'count': 50, 'method': 'priority'
            },
            '全面复习': {
                'ranks': Vocabulary.rank_table,
                'times': ['已逾期', '今早', '今晚', '明早', '明晚', '后天'],
                'len_min': 1, 'len_max': 20,
                'letters': list('ABCDEFGHIJKLMNOPQRSTUVWXYZ'),
                'assoc_filter': '全部', 'notes_filter': '全部',
                'count': 100, 'method': 'proportion'
            },
            '新词学习': {
                'ranks': ['待定'],
                'times': [],
                'len_min': 1, 'len_max': 20,
                'letters': list('ABCDEFGHIJKLMNOPQRSTUVWXYZ'),
                'assoc_filter': '全部', 'notes_filter': '无笔记',
                'count': 30, 'method': 'priority'
            },
            '难点攻克': {
                'ranks': ['忘记', '顽固'],
                'times': ['已逾期', '今早', '今晚', '明早', '明晚', '后天',
                          '第4天', '第7天', '第15天', '半个月后'],
                'len_min': 1, 'len_max': 20,
                'letters': list('ABCDEFGHIJKLMNOPQRSTUVWXYZ'),
                'assoc_filter': '全部', 'notes_filter': '全部',
                'count': 30, 'method': 'priority'
            }
        }

    def _save_presets(self):
        """保存预设到文件"""
        try:
            os.makedirs(os.path.dirname(PRESET_PATH), exist_ok=True)
            with open(PRESET_PATH, 'w', encoding='utf-8') as f:
                json.dump(self.presets, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error('保存预设失败: {}'.format(e))

    def _refresh_preset_combo(self):
        """刷新预设下拉列表"""
        self.preset_combo.clear()
        for name in sorted(self.presets.keys()):
            self.preset_combo.addItem(name)

    def _save_preset(self):
        """保存当前配置为预设"""
        name, ok = QInputDialog.getText(self, '保存预设', '请输入预设名称:')
        if ok and name.strip():
            name = name.strip()
            self.presets[name] = self._get_current_config()
            self._save_presets()
            self._refresh_preset_combo()
            self.preset_combo.setCurrentText(name)
            QMessageBox.information(self, '保存成功', '预设 "{}" 已保存'.format(name))

    def _load_preset(self):
        """加载选中的预设"""
        name = self.preset_combo.currentText()
        if not name or name not in self.presets:
            QMessageBox.warning(self, '提示', '请先选择一个预设')
            return
        config = self.presets[name]
        try:
            # 恢复掌握度选择
            self._set_selected_items(self.ranks_list, config.get('ranks', []))
            # 恢复时间选择
            self._set_selected_items(self.times_list, config.get('times', []))
            # 恢复长度滑条
            self.len_min_slider.setValue(config.get('len_min', 1))
            self.len_max_slider.setValue(config.get('len_max', 20))
            # 恢复首字母
            selected_letters = set(config.get('letters', list('ABCDEFGHIJKLMNOPQRSTUVWXYZ')))
            for letter, cb in self.letter_checks.items():
                cb.setChecked(letter in selected_letters)
            # 恢复过滤选项
            self.assoc_combo.setCurrentText(config.get('assoc_filter', '全部'))
            # 兼容旧预设：如果是record_filter则映射到notes_filter
            if 'notes_filter' in config:
                self.notes_combo.setCurrentText(config.get('notes_filter', '全部'))
            elif 'record_filter' in config:
                # 旧预设的record_filter映射：从未复习->无笔记，有复习记录->全部
                old_val = config.get('record_filter', '全部')
                mapping = {'从未复习': '无笔记', '有复习记录': '全部', '全部': '全部'}
                self.notes_combo.setCurrentText(mapping.get(old_val, '全部'))
            # 恢复数量
            self.countSlider.setValue(config.get('count', 100))
            # 恢复提取方式
            if config.get('method', 'proportion') == 'priority':
                self.radioPriority.setChecked(True)
            else:
                self.radioProportion.setChecked(True)
            self._refresh_preview()
            QMessageBox.information(self, '加载成功', '预设 "{}" 已加载'.format(name))
        except Exception as e:
            QMessageBox.warning(self, '加载失败', str(e))

    def _delete_preset(self):
        """删除选中的预设"""
        name = self.preset_combo.currentText()
        if not name or name not in self.presets:
            return
        reply = QMessageBox.question(
            self, '确认删除', '确定要删除预设 "{}" 吗？'.format(name),
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            del self.presets[name]
            self._save_presets()
            self._refresh_preset_combo()

    @staticmethod
    def _set_selected_items(list_widget, selected_texts):
        """设置列表控件的选中项"""
        selected_set = set(selected_texts)
        for i in range(list_widget.count()):
            item = list_widget.item(i)
            item.setSelected(item.text() in selected_set)

    def _get_current_config(self):
        """获取当前配置（用于保存预设）"""
        return {
            'ranks': self._get_selected_ranks(),
            'times': self._get_selected_times(),
            'len_min': self.len_min_slider.value(),
            'len_max': self.len_max_slider.value(),
            'letters': self._get_selected_letters(),
            'assoc_filter': self.assoc_combo.currentText(),
            'notes_filter': self.notes_combo.currentText(),
            'count': self.countSlider.value(),
            'method': 'priority' if self.radioPriority.isChecked() else 'proportion'
        }

    def accept(self):
        """确认按钮 - 应用筛选并开始复习"""
        ranks = self._get_selected_ranks()
        times = self._get_selected_times()
        count = self.countSlider.value()

        # 清空现有复习列表
        self.book.reviewList.clear()
        self.book.masterySet.clear()
        self.book.vagueSet.clear()
        self.book.forgetList.clear()
        self.book.CheckMode = True

        # 获取筛选后的单词并应用选择方法
        filtered_words = self._get_filtered_words()
        if not filtered_words:
            QMessageBox.warning(self, '提示', '没有符合条件的单词，请调整筛选条件！')
            return

        if self.radioProportion.isChecked():
            self._select_by_proportion(filtered_words, count)
        else:
            self._select_by_priority(filtered_words, count)

        if len(self.book.reviewList) == 0:
            QMessageBox.warning(self, '提示', '筛选结果为空，请调整条件！')
            return

        super().accept()

    def _select_by_proportion(self, words, count):
        """按比例抽取"""
        from collections import defaultdict
        import math
        temp = defaultdict(list)
        for word in words:
            if word not in self.book.reviewList:
                temp[word.rank].append(word)
        total = sum(map(len, temp.values()))
        for value in temp.values():
            n = math.ceil(len(value) / total * count) if total > 0 else 0
            self.book.reviewList.extend(value[:n])
        logger.info('比例抽取: {} 个单词'.format(len(self.book.reviewList)))

    def _select_by_priority(self, words, count):
        """按优先级抽取"""
        for i, word in enumerate(words):
            if i >= count:
                break
            if word not in self.book.reviewList:
                self.book.reviewList.append(word)
        logger.info('优先级抽取: {} 个单词'.format(len(self.book.reviewList)))
