# -*- coding: utf-8 -*-
# @Time    : 2018/1/17 下午10:27
# @Author  : BiarFordlander
# @Email   : B****************@*********
# @File    : MainEngine.py
# @Software: PyCharm
# @Description: 主引擎 - 集成力导向图面板、报告窗口、增强配置界面
from SmartReview.UI import UIBase, UIConfig, UISearch
from PyQt5.QtCore import pyqtSlot, pyqtSignal
from PyQt5.QtWidgets import (
    QMainWindow, QDialog, QTableWidgetItem, QTableWidget, QAction,
    QMenuBar, QMenu, QMessageBox, QPushButton, QHBoxLayout, QWidget,
    QToolBar, QStatusBar, QLabel
)
from PyQt5.QtCore import Qt, QObject
from PyQt5 import QtGui
from SmartReview.Tactics import LearnTactics
import re
from SmartReview.Base import Record
from SmartReview.Base import Dictionary, Vocabulary
import json
import time
import logging
from SmartReview.Tools import pysay

# 新增模块导入
from SmartReview.GraphPanel import GraphPanelDialog
from SmartReview.ReportWindow import ReportWindow
from SmartReview.ConfigEnhanced import ConfigEnhancedDialog

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class SearchDialog(QDialog, UISearch.Ui_Dialog):
    """ 单词搜索/添加关联词对话框（保留原有功能） """

    def __init__(self, *args, **kwargs):
        self.book = kwargs.pop('book')
        self.mainwindow = kwargs.pop('mainwindow')
        super(SearchDialog, self).__init__(*args, **kwargs)
        self.setupUi(self)

        self.set_tableContent(['单词', '释义'], self.wordsTable, self.find())
        self.wordEdit.textChanged.connect(self.autofind)
        self.explainEdit.textChanged.connect(self.autofind)

    @classmethod
    def LoadFrom(cls, book, mainwindow):
        assert isinstance(book, Dictionary), "book 必须是 Dictionary 类型!"
        return cls(book=book, mainwindow=mainwindow)

    def show(self):
        self.wordEdit.setText('')
        self.explainEdit.setText('')
        super(SearchDialog, self).show()

    @pyqtSlot()
    def autofind(self):
        """ 自动寻找并且刷新列表 """
        word_pattern = self.wordEdit.text() if self.wordEdit.text() else '.*'
        explain_pattern = self.explainEdit.text() if self.explainEdit.text() else '.*'
        result = self.find(word_pattern, explain_pattern)
        self.set_tableContent(['单词', '释义'], self.wordsTable, result)

    def find(self, word_pattern='.*', explain_pattern='.*'):
        """ 从当前单词库中寻找已经存在的单词 """
        word_pattern = word_pattern.strip('\\[]')
        explain_pattern = explain_pattern.strip('\\[]')
        if word_pattern == explain_pattern == '.*':
            return dict()
        else:
            if isinstance(self.book, Dictionary):
                result = {word.value: word.explain for word in self.book.values() if
                          re.search(word_pattern, word.value) and re.search(explain_pattern, word.explain)}
            else:
                result = {word: explain for word, explain in self.book.items() if
                          re.search(word_pattern, word) and re.search(explain_pattern, explain)}
            return result

    @staticmethod
    def set_tableContent(headerlabels, table, source):
        """ 用来设置列表的内容 """
        assert isinstance(source, dict), "参数 source 应当是一个 Dict 对象"
        table.setHorizontalHeaderLabels(headerlabels)
        table.setColumnCount(2)
        table.setRowCount(len(source))
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.SingleSelection)
        for index, content in enumerate(source.items()):
            table.setItem(index, 0, QTableWidgetItem(str(content[0])))
            table.setItem(index, 1, QTableWidgetItem(str(content[1]).replace('\n', ' ')))
        table.resizeColumnsToContents()

    def accept(self):
        """ 点击接受 - 添加关联词 """
        if self.wordsTable.selectedIndexes():
            word, explain = self.wordsTable.selectedIndexes()
            word = word.data()
            if self.mainwindow.word:
                cur_word = self.mainwindow.word
                cur_word.associate.add(word)
                # 双向关联
                if word in self.book:
                    self.book[word].associate.add(cur_word.value)
            else:
                logger.warning('当前没有正在背的单词,添加关联词失败!')
        super(SearchDialog, self).accept()


class ConfigDialog(QDialog, UIConfig.Ui_Dialog):
    """ 旧版配置对话框（保留兼容） """

    def __init__(self, *args, **kwargs):
        super(ConfigDialog, self).__init__(*args, **kwargs)
        self.setupUi(self)
        self.book = LearnTactics.loadFrom()

        self.set_tableContent(['程度', '数量'], self.ranksTable, self.book.info_ranks, Vocabulary.default_ranks_chooses())
        self.set_tableContent(['时间', '数量'], self.timesTable, self.book.info_times, Vocabulary.default_times_chooses())
        self.countSlider.valueChanged.connect(self.countLCD.display)
        self.ranksTable.itemSelectionChanged.connect(self.flush_selectedLCD)
        self.timesTable.itemSelectionChanged.connect(self.flush_selectedLCD)
        self.flush_selectedLCD()
        self.set_slider(self.countSlider)

    def flush_selectedLCD(self):
        ranks = self.get_selected_key(self.ranksTable)
        times = self.get_selected_key(self.timesTable)
        self.selectedLCD.display(self.book.size_of_needreview(ranks, times))

    @staticmethod
    def set_slider(slider, min=10, max=120, default=100):
        slider.setMinimum(min)
        slider.setMaximum(max)
        slider.setValue(default)

    @staticmethod
    def set_tableContent(headerlabels, table, source, default_chooses=None):
        if default_chooses is None:
            default_chooses = list()
        assert isinstance(source, dict), "参数 source 应当是一个 Dict 对象"
        table.setHorizontalHeaderLabels(headerlabels)
        table.setRowCount(len(source))
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.MultiSelection)
        for index, content in enumerate(source.items()):
            table.setItem(index, 0, QTableWidgetItem(str(content[0])))
            table.setItem(index, 1, QTableWidgetItem(str(content[1])))
            if content[0] in default_chooses:
                table.selectRow(index)
        table.resizeColumnsToContents()

    @staticmethod
    def get_selected_key(table):
        return [line.data() for line in table.selectedIndexes() if line.column() == 0]

    @staticmethod
    def get_selected_value(table):
        return [line.data() for line in table.selectedIndexes() if line.column() == 1]

    def accept(self):
        ranks = self.get_selected_key(self.ranksTable)
        times = self.get_selected_key(self.timesTable)
        if self.radioProportion.isChecked():
            self.book.select_by_proportion(ranks, times, count=self.countSlider.value())
        elif self.radioPriority.isChecked():
            self.book.select(ranks, times, count=self.countSlider.value())
        else:
            raise NotImplementedError('你选择的算法暂时还没有实现!')
        super(ConfigDialog, self).accept()


class MainWindow(QMainWindow, UIBase.Ui_MainWindow):
    """ 主窗口 - 集成图面板、报告、增强配置 """

    def __init__(self, *args, **kwargs):
        super(MainWindow, self).__init__(*args, **kwargs)
        self.setupUi(self)

        # 使用增强版配置对话框替代旧版
        self.book = LearnTactics.loadFrom()
        self.searchDialog = SearchDialog.LoadFrom(self.book, self)
        self.graphDialog = None
        self.reportDialog = None
        self.enhancedConfigDialog = None

        self.word = None
        self.completed = False
        self.timeStart = None
        self.timeEnd = None
        self.timeSpeed = None
        self.word_explain.hide()
        self.word_status.hide()

        # 添加新按钮和菜单栏
        self._setup_menubar()
        self._setup_extra_buttons()
        self.install_signals_and_slots()

        if len(self.book) > 0 and len(self.book.reviewList) == 0:
            self.book.select(count=100)

        # 状态栏信息
        self.statusBar().showMessage('按 Ctrl 下一个单词 | Alt 切换忘记/朗读 | ESC 保存 | 菜单查看更多功能')

    def _setup_menubar(self):
        """ 设置菜单栏 """
        menubar = self.menuBar()

        # 工具菜单
        tools_menu = menubar.addMenu('工具(&T)')

        # 全局有向图
        action_graph = QAction('🌐 单词关联图谱', self)
        action_graph.setShortcut('Ctrl+G')
        action_graph.setStatusTip('打开力导向图查看单词关联关系')
        action_graph.triggered.connect(self.show_graph_panel)
        tools_menu.addAction(action_graph)

        # 学习报告
        action_report = QAction('📊 学习报告', self)
        action_report.setShortcut('Ctrl+R')
        action_report.setStatusTip('查看学习数据统计报告')
        action_report.triggered.connect(self.show_report)
        tools_menu.addAction(action_report)

        tools_menu.addSeparator()

        # 增强配置
        action_config_enhanced = QAction('⚙️ 增强配置', self)
        action_config_enhanced.setShortcut('Ctrl+E')
        action_config_enhanced.setStatusTip('打开增强版复习配置界面')
        action_config_enhanced.triggered.connect(self.show_enhanced_config)
        tools_menu.addAction(action_config_enhanced)

        # 旧版配置
        action_config_old = QAction('🔧 经典配置（旧版）', self)
        action_config_old.setStatusTip('使用经典版配置界面')
        action_config_old.triggered.connect(self._show_old_config)
        tools_menu.addAction(action_config_old)

        tools_menu.addSeparator()

        # 保存
        action_save = QAction('💾 保存', self)
        action_save.setShortcut('Ctrl+S')
        action_save.setStatusTip('保存当前进度')
        action_save.triggered.connect(self._save_progress)
        tools_menu.addAction(action_save)

        # 帮助菜单
        help_menu = menubar.addMenu('帮助(&H)')
        action_about = QAction('关于 SmartReview', self)
        action_about.triggered.connect(self._show_about)
        help_menu.addAction(action_about)

    def _setup_extra_buttons(self):
        """ 在主界面添加额外按钮 """
        # 在原有关联词按钮旁边添加新按钮
        btn_graph = QPushButton('🌐 图谱', self.centralwidget)
        btn_graph.setGeometry(470, 460, 80, 32)
        btn_graph.setToolTip('查看单词关联图谱（力导向图）')
        btn_graph.clicked.connect(self.show_graph_panel)

        btn_report = QPushButton('📊 报告', self.centralwidget)
        btn_report.setGeometry(560, 460, 80, 32)
        btn_report.setToolTip('查看学习报告')
        btn_report.clicked.connect(self.show_report)

        btn_config = QPushButton('⚙️ 配置', self.centralwidget)
        btn_config.setGeometry(650, 460, 80, 32)
        btn_config.setToolTip('增强配置')
        btn_config.clicked.connect(self.show_enhanced_config)

    def install_signals_and_slots(self):
        """ 安装信号槽 """
        self.auto_speaker.toggled[bool].connect(self.muteEvent)
        self.word_status.toggled[bool].connect(self.switchStatus)
        self.configButton.clicked[bool].connect(self.show_enhanced_config)  # 头像按钮改为增强配置
        self.associationButton.clicked[bool].connect(self.show_graph_panel)  # 关联词按钮改为打开图谱

    def show_graph_panel(self):
        """ 显示全局有向图面板 """
        if self.graphDialog is None:
            self.graphDialog = GraphPanelDialog(self.book, self)
            self.graphDialog.word_jump_requested.connect(self._jump_to_word_from_graph)
            self.graphDialog.graph_modified.connect(self._on_graph_modified)
        else:
            self.graphDialog.refresh()
        self.graphDialog.show()

    def _jump_to_word_from_graph(self, word_text):
        """ 从图谱跳转到指定单词 """
        if word_text in self.book.data:
            target_word = self.book.data[word_text]
            # 检查单词是否在复习列表中
            if target_word in self.book.reviewList:
                # 将目标单词移到队列前端
                self.book.reviewList.remove(target_word)
                self.book.reviewList.appendleft(target_word)
                QMessageBox.information(self, '跳转成功',
                                        '单词 "{}" 已移至复习队列前端，按 Ctrl 继续学习'.format(word_text))
            else:
                QMessageBox.information(self, '提示',
                                        '单词 "{}" 不在当前复习队列中，请先在配置中选中该单词'.format(word_text))
        else:
            QMessageBox.warning(self, '未找到', '单词 "{}" 不存在于词库中'.format(word_text))

    def _on_graph_modified(self):
        """ 图谱被修改（删除关联等） """
        logger.info('图谱已修改，关联词已更新')

    def show_report(self):
        """ 显示学习报告窗口 """
        if self.reportDialog is None:
            self.reportDialog = ReportWindow(self.book, self)
        else:
            self.reportDialog._refresh()
        self.reportDialog.show()

    def show_enhanced_config(self):
        """ 显示增强配置对话框 """
        # 每次创建新对话框以确保数据最新
        dialog = ConfigEnhancedDialog(self.book, self)
        if dialog.exec_() == QDialog.Accepted:
            # 用户确认后，重置学习状态
            self.completed = False
            self.word = None
            self.word_explain.hide()
            self.word_status.show()
            self.auto_speaker.show()
            self.word_current.show()
            self.word_current.setText('按 Ctrl 开始')
            self.word_before.setText('即将开始')
            self.speed_progress.setValue(0)
            self.statusBar().showMessage('已选择 {} 个单词，按 Ctrl 开始复习'.format(len(self.book.reviewList)))
            if self.graphDialog:
                self.graphDialog.refresh()

    def _show_old_config(self):
        """ 显示旧版配置对话框 """
        old_dialog = ConfigDialog(self)
        if old_dialog.exec_() == QDialog.Accepted:
            self.book = old_dialog.book
            self.completed = False
            self.word = None
            self.word_explain.hide()
            self.word_status.show()
            self.auto_speaker.show()
            self.word_current.show()
            self.word_current.setText('按 Ctrl 开始')
            self.speed_progress.setValue(0)

    def _save_progress(self):
        """ 保存进度 """
        self.book.save()
        self.say('已保存!')
        self.word_before.setText('已保存')
        self.statusBar().showMessage('进度已保存 - {}'.format(time.strftime('%H:%M:%S')))

    def _show_about(self):
        """ 显示关于对话框 """
        QMessageBox.about(self, '关于 SmartReview',
                          '📚 SmartReview - 智能复习工具\n\n'
                          '版本: 2.0 (增强版)\n'
                          '功能: 力导向图 | 学习报告 | 增强配置\n\n'
                          '操作提示:\n'
                          '• Ctrl: 下一个单词\n'
                          '• Alt: 切换忘记/朗读\n'
                          '• ESC: 保存进度\n'
                          '• Ctrl+G: 图谱\n'
                          '• Ctrl+R: 报告\n'
                          '• Ctrl+E: 增强配置')

    @pyqtSlot(bool)
    def muteEvent(self, turn_on):
        """ 配置是否智能朗读单词 """
        if turn_on is True:
            self.say('已开启智能朗读')
            self.auto_speaker.setText('智能朗读')
        else:
            self.auto_speaker.setText('已静音')
        logger.info('[MODE_SWITCH] mute is {}'.format(not turn_on))

    @pyqtSlot(bool)
    def switchStatus(self, status):
        """ 切换单词的状态 """
        if status is True:
            self.word_status.setText('已记住')
            self.word_explain.setStyleSheet('QLabel {background-color: none}')
        else:
            self.say('已忘记')
            self.word_status.setText('已忘记')
            if self.book.CheckMode is False:
                self.word_explain.setStyleSheet('QLabel {background-color: gray}')
        logger.debug('[STAUTS_SWITCH] word_status is {}'.format(status))

    def saveStatus(self):
        """ 设置单词的状态 """
        if self.word_status.isChecked():
            self.book.add_remember(self.word)
            logger.debug("{} marked remember".format(self.word.value))
        else:
            self.book.add_forget(self.word)
            logger.warning("{} marked forget".format(self.word.value))

    def switchWord(self):
        """ 切换到下一个单词 """
        if self.word is not None:
            self.saveStatus()
            if self.timeStart > self.timeEnd:
                record = Record(speed=self.timeSpeed, timestamp=self.timeStart,
                                stats=self.word_status.isChecked())
                logger.debug('{} added a new record: {}'.format(self.word_before.text(), record))
                self.word.daylog.add_record(record)
        try:
            self.word_explain.hide()
            self.word_current.show()
            self.word = self.book.fetch()
            self.word_status.setChecked(True)
        except KeyError:
            self.say('已全部检查完毕! 按 ESC 保存，或查看报告')
            self.completed = True
            self.word_current.setText('已全部检查完毕!')
            self.word = None
            # 完成后自动询问是否查看报告
            reply = QMessageBox.question(
                self, '复习完成',
                '本次复习已完成！是否查看学习报告？',
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
            )
            if reply == QMessageBox.Yes:
                self.show_report()
        else:
            if self.book.CheckMode is False:
                self.say(self.word.value, speaker='Ava')
            self.word_current.setText(self.word.value)

    def setExplain(self):
        """ 设置释义与进度 """
        self.word_current.hide()
        self.word_explain.show()
        if self.completed is True:
            smalltitle = '待保存...'
            explain = self.book.save_and_get_report()
            association = None
        else:
            smalltitle = self.word.value
            explain = self.word.explain
            association = ' | '.join(self.word.associate)
        self.word_explain.setText(explain)
        self.word_explain.setAlignment(Qt.AlignCenter)
        self.word_before.setText(smalltitle)
        self.associationLabel.setText(association if association else '暂无关联词')
        progress = round(self.book.process * 100, 2)
        self.speed_progress.setValue(self.book.process * 100)
        self.statusBar().showMessage('进度: {}%'.format(progress))
        if self.completed is True:
            self.word_status.hide()
            self.auto_speaker.hide()
        else:
            self.word_status.show()
            self.auto_speaker.show()

    def keyPressEvent(self, QKeyEvent):
        """ 按下事件 """
        if QKeyEvent.key() == Qt.Key_Control:
            logger.debug('key:{} is press'.format('Key_Control'))
            self.timeStart = time.time()
            self.switchWord()
        elif QKeyEvent.key() == Qt.Key_Alt:
            logger.debug('key:{} is press'.format('Key_Alt'))
            if self.word:
                if self.word_status.isChecked():
                    self.word_status.setChecked(False)
                else:
                    self.say(self.word.value, speaker='Ava')

    def keyReleaseEvent(self, QKeyEvent):
        """ 松开事件 """
        if QKeyEvent.key() == Qt.Key_Control:
            logger.debug('key:{} is release'.format('Key_Control'))
            self.timeEnd = time.time()
            self.timeSpeed = self.timeEnd - self.timeStart
            self.setExplain()
        if QKeyEvent.key() == Qt.Key_Escape:
            self.book.save()
            self.say('已保存!')
            self.word_before.setText('已保存')
            self.statusBar().showMessage('进度已保存 - {}'.format(time.strftime('%H:%M:%S')))
            # 刷新图谱颜色
            if self.graphDialog:
                self.graphDialog.refresh()

    def say(self, text, speaker=None, speed=4):
        """ 语音朗读 """
        if self.auto_speaker.isChecked() is False:
            text = ''
        pysay.say(text, speaker, speed)


def main():
    from PyQt5.QtWidgets import QApplication
    import sys

    app = QApplication(sys.argv)
    app.setApplicationName('SmartReview')
    xx = MainWindow()
    xx.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
