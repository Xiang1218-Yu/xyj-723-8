# -*- coding: utf-8 -*-
# @File    : GraphPanel.py
# @Description: 全局有向图面板 - 力导向图展示单词节点与关联关系
import math
import random
import logging
from PyQt5.QtCore import Qt, QPointF, QRectF, pyqtSignal, QTimer
from PyQt5.QtGui import QColor, QBrush, QPen, QFont, QPainter, QPainterPath
from PyQt5.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsItem, QGraphicsEllipseItem,
    QGraphicsTextItem, QGraphicsLineItem, QDialog, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPushButton, QLabel, QWidget, QMenu, QMessageBox, QComboBox
)

logger = logging.getLogger(__name__)


# 掌握度对应的颜色映射表 (rank -> QColor)
RANK_COLORS = {
    '精通': QColor(46, 204, 113),    # 绿色 - 最熟练
    '掌握': QColor(52, 152, 219),    # 蓝色
    '记住': QColor(155, 89, 182),    # 紫色
    '清晰': QColor(26, 188, 156),    # 青绿色
    '模糊': QColor(241, 196, 15),    # 黄色
    '混淆': QColor(230, 126, 34),    # 橙色
    '忘记': QColor(231, 76, 60),     # 红色
    '顽固': QColor(192, 57, 43),     # 深红色
    '待定': QColor(149, 165, 166),   # 灰色 - 未定义
}


class WordNode(QGraphicsEllipseItem):
    """单词节点类 - 在力导向图中表示一个单词"""

    def __init__(self, word_obj, radius=20, parent=None):
        """
        初始化单词节点
        :param word_obj: Vocabulary对象
        :param radius: 节点半径
        """
        super().__init__(-radius, -radius, radius * 2, radius * 2, parent)
        self.word_obj = word_obj
        self.word_text = word_obj.value
        self.radius = radius

        # 力导向模拟相关属性
        self.vel = QPointF(0, 0)       # 速度
        self.pos = QPointF(0, 0)       # 当前位置
        self.force = QPointF(0, 0)     # 合力

        # 设置节点外观
        self.setAcceptHoverEvents(True)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setBrush(QBrush(self._get_color()))
        self.setPen(QPen(QColor(255, 255, 255), 2))
        self.setZValue(10)

        # 添加文本标签
        self.label = QGraphicsTextItem(self.word_text, self)
        self.label.setDefaultTextColor(QColor(30, 30, 30))
        font = QFont("Arial", 8)
        self.label.setFont(font)
        # 将文本居中放置在节点下方
        text_rect = self.label.boundingRect()
        self.label.setPos(-text_rect.width() / 2, radius + 2)
        self.label.setZValue(11)

        # 高亮状态
        self.highlighted = False
        self.neighbors = set()  # 邻居节点集合

    def _get_color(self):
        """根据单词掌握度获取颜色"""
        rank = self.word_obj.rank
        return RANK_COLORS.get(rank, RANK_COLORS['待定'])

    def update_color(self):
        """更新节点颜色（当掌握度变化时调用）"""
        self.setBrush(QBrush(self._get_color()))

    def get_rank(self):
        """获取当前掌握度"""
        return self.word_obj.rank

    def set_highlight(self, highlight, is_neighbor=False):
        """设置节点高亮状态"""
        self.highlighted = highlight
        if highlight:
            if is_neighbor:
                # 邻居节点：青绿色边框加粗
                self.setPen(QPen(QColor(26, 188, 156), 4))
                self.setScale(1.15)
            else:
                # 当前选中节点：金黄色边框加粗
                self.setPen(QPen(QColor(241, 196, 15), 5))
                self.setScale(1.3)
            self.setZValue(20)
        else:
            self.setPen(QPen(QColor(255, 255, 255), 2))
            self.setScale(1.0)
            self.setZValue(10)

    def apply_force(self, force_x, force_y):
        """施加力到节点"""
        self.force += QPointF(force_x, force_y)

    def step(self, damping=0.85, max_speed=15.0):
        """力导向模拟一步更新
        :param damping: 阻尼系数 (0-1)
        :param max_speed: 最大速度限制
        """
        self.vel = (self.vel + self.force) * damping
        # 限制最大速度
        speed = math.hypot(self.vel.x(), self.vel.y())
        if speed > max_speed:
            self.vel *= max_speed / speed
        self.pos += self.vel
        self.setPos(self.pos)
        self.force = QPointF(0, 0)


class EdgeLine(QGraphicsLineItem):
    """边/关联线类 - 表示两个单词之间的关联关系"""

    def __init__(self, source_node, target_node, parent=None):
        """
        初始化边
        :param source_node: 起始节点
        :param target_node: 目标节点
        """
        super().__init__(parent)
        self.source = source_node
        self.target = target_node
        self.setPen(QPen(QColor(180, 180, 180, 120), 1.5))
        self.setZValue(1)
        self.highlighted = False
        self._update_position()

    def _update_position(self):
        """更新边的位置（跟随节点移动）"""
        if self.source and self.target:
            self.setLine(
                self.source.pos().x(), self.source.pos().y(),
                self.target.pos().x(), self.target.pos().y()
            )

    def set_highlight(self, highlight):
        """设置边高亮状态"""
        self.highlighted = highlight
        if highlight:
            self.setPen(QPen(QColor(52, 152, 219), 3))
            self.setZValue(15)
        else:
            self.setPen(QPen(QColor(180, 180, 180, 120), 1.5))
            self.setZValue(1)


class ForceDirectedScene(QGraphicsScene):
    """力导向图场景 - 管理节点和边的物理模拟"""

    # 力导向参数
    REPULSION = 8000       # 斥力常数
    ATTRACTION = 0.01      # 引力常数（弹簧）
    DAMPING = 0.85         # 阻尼系数
    MAX_SPEED = 12.0       # 最大速度
    CENTER_GRAVITY = 0.005 # 中心引力
    IDEAL_DISTANCE = 150   # 理想弹簧长度
    SIMULATION_STEPS = 3   # 每次定时器触发的模拟步数

    def __init__(self, parent=None):
        super().__init__(parent)
        self.nodes = {}       # word_text -> WordNode
        self.edges = []       # EdgeLine列表
        self.timer = QTimer()
        self.timer.timeout.connect(self._simulate_step)
        self.is_simulating = False
        self.temperature = 1.0  # 模拟温度（随时间降低）

    def build_graph(self, dictionary):
        """从Dictionary对象构建图
        :param dictionary: Dictionary对象（词库）
        """
        self.clear_all()

        words = list(dictionary.values())
        if not words:
            return

        # 创建节点
        center = QPointF(0, 0)
        for word_obj in words:
            node = WordNode(word_obj)
            # 随机初始位置
            angle = random.uniform(0, 2 * math.pi)
            dist = random.uniform(50, 300)
            node.pos = QPointF(
                center.x() + math.cos(angle) * dist,
                center.y() + math.sin(angle) * dist
            )
            node.setPos(node.pos)
            self.addItem(node)
            self.nodes[word_obj.value] = node

        # 创建边（关联关系）
        for word_obj in words:
            source_node = self.nodes.get(word_obj.value)
            if not source_node:
                continue
            for assoc_text in word_obj.associate:
                target_node = self.nodes.get(assoc_text)
                if target_node and assoc_text > word_obj.value:  # 避免重复边
                    edge = EdgeLine(source_node, target_node)
                    self.addItem(edge)
                    self.edges.append(edge)
                    source_node.neighbors.add(target_node)
                    target_node.neighbors.add(source_node)

        self.setSceneRect(-500, -500, 1000, 1000)
        self.start_simulation()

    def clear_all(self):
        """清空场景"""
        self.nodes.clear()
        self.edges.clear()
        self.clear()

    def start_simulation(self):
        """启动力导向模拟"""
        self.temperature = 1.0
        self.is_simulating = True
        self.timer.start(30)  # 约33fps

    def stop_simulation(self):
        """停止力导向模拟"""
        self.is_simulating = False
        self.timer.stop()

    def _simulate_step(self):
        """执行一步物理模拟"""
        if not self.is_simulating:
            return

        for _ in range(self.SIMULATION_STEPS):
            self.temperature *= 0.995  # 退火降温
            if self.temperature < 0.05:
                self.stop_simulation()
                break

            node_list = list(self.nodes.values())

            # 计算斥力（节点之间）
            for i, n1 in enumerate(node_list):
                for n2 in node_list[i + 1:]:
                    delta = n1.pos - n2.pos
                    dist_sq = delta.x() ** 2 + delta.y() ** 2
                    if dist_sq < 1:
                        dist_sq = 1
                    dist = math.sqrt(dist_sq)
                    # 斥力与距离平方成反比
                    force = self.REPULSION / dist_sq * self.temperature
                    fx = delta.x() / dist * force
                    fy = delta.y() / dist * force
                    n1.apply_force(fx, fy)
                    n2.apply_force(-fx, -fy)

            # 计算引力（弹簧边）
            for edge in self.edges:
                delta = edge.target.pos - edge.source.pos
                dist = math.sqrt(delta.x() ** 2 + delta.y() ** 2)
                if dist < 1:
                    dist = 1
                # 胡克定律
                force = (dist - self.IDEAL_DISTANCE) * self.ATTRACTION * self.temperature
                fx = delta.x() / dist * force
                fy = delta.y() / dist * force
                edge.source.apply_force(fx, fy)
                edge.target.apply_force(-fx, -fy)

            # 中心引力
            for node in node_list:
                node.apply_force(
                    -node.pos.x() * self.CENTER_GRAVITY * self.temperature,
                    -node.pos.y() * self.CENTER_GRAVITY * self.temperature
                )

            # 更新位置
            for node in node_list:
                node.step(self.DAMPING, self.MAX_SPEED * self.temperature)

            # 更新边位置
            for edge in self.edges:
                edge._update_position()

    def highlight_neighbors(self, selected_node):
        """高亮选中节点及其邻居
        :param selected_node: 选中的WordNode，None则取消所有高亮
        """
        # 先重置所有高亮
        for node in self.nodes.values():
            node.set_highlight(False)
        for edge in self.edges:
            edge.set_highlight(False)

        if selected_node is None:
            return

        # 高亮选中节点
        selected_node.set_highlight(True)

        # 高亮邻居节点和连接边
        for edge in self.edges:
            if edge.source == selected_node:
                edge.target.set_highlight(True, is_neighbor=True)
                edge.set_highlight(True)
            elif edge.target == selected_node:
                edge.source.set_highlight(True, is_neighbor=True)
                edge.set_highlight(True)

    def filter_by_text(self, filter_text):
        """根据搜索文本过滤节点
        :param filter_text: 搜索关键词，空字符串则显示全部
        """
        filter_text = filter_text.strip().lower()
        for text, node in self.nodes.items():
            if not filter_text or filter_text in text.lower():
                node.setVisible(True)
                node.label.setVisible(True)
            else:
                node.setVisible(False)
                node.label.setVisible(False)
        # 显示/隐藏边
        for edge in self.edges:
            if edge.source.isVisible() and edge.target.isVisible():
                edge.setVisible(True)
            else:
                edge.setVisible(False)


class GraphView(QGraphicsView):
    """力导向图视图 - 支持缩放平移和交互"""

    word_double_clicked = pyqtSignal(str)  # 单词双击信号，传递单词文本
    association_removed = pyqtSignal(str, str)  # 关联删除信号，传递两个单词

    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene = ForceDirectedScene()
        self.setScene(self.scene)

        # 视图设置
        self.setRenderHint(QPainter.Antialiasing)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.ScrollHandDrag)  # 拖拽平移
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setBackgroundBrush(QBrush(QColor(250, 250, 250)))

        # 选中节点
        self.selected_node = None

        # 右键菜单
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    def load_dictionary(self, dictionary):
        """加载词库并构建图
        :param dictionary: Dictionary对象
        """
        self.scene.build_graph(dictionary)
        self.fitInView(self.scene.itemsBoundingRect(), Qt.KeepAspectRatio)

    def refresh_colors(self):
        """刷新所有节点颜色（掌握度变化时调用）"""
        for node in self.scene.nodes.values():
            node.update_color()

    def wheelEvent(self, event):
        """鼠标滚轮缩放"""
        zoom_factor = 1.15
        if event.angleDelta().y() > 0:
            self.scale(zoom_factor, zoom_factor)
        else:
            self.scale(1 / zoom_factor, 1 / zoom_factor)

    def mousePressEvent(self, event):
        """鼠标点击事件"""
        if event.button() == Qt.LeftButton:
            # 查找点击的节点
            item = self.itemAt(event.pos())
            # 如果点击的是文本标签，获取其父节点
            if isinstance(item, QGraphicsTextItem) and item.parentItem():
                item = item.parentItem()
            if isinstance(item, WordNode):
                self.selected_node = item
                self.scene.highlight_neighbors(item)
            else:
                self.selected_node = None
                self.scene.highlight_neighbors(None)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        """鼠标双击事件 - 跳转到单词"""
        if event.button() == Qt.LeftButton:
            item = self.itemAt(event.pos())
            if isinstance(item, QGraphicsTextItem) and item.parentItem():
                item = item.parentItem()
            if isinstance(item, WordNode):
                self.word_double_clicked.emit(item.word_text)
                logger.info('双击跳转到单词: {}'.format(item.word_text))
        super().mouseDoubleClickEvent(event)

    def _show_context_menu(self, pos):
        """显示右键菜单"""
        item = self.itemAt(pos)
        if isinstance(item, QGraphicsTextItem) and item.parentItem():
            item = item.parentItem()
        if not isinstance(item, WordNode):
            return

        menu = QMenu(self)

        # 如果有选中的其他节点，提供删除关联选项
        if self.selected_node and self.selected_node != item:
            action_remove = menu.addAction(
                '删除关联: {} <-> {}'.format(self.selected_node.word_text, item.word_text)
            )
            action_remove.triggered.connect(
                lambda: self._remove_association(self.selected_node, item)
            )
            menu.addSeparator()

        action_jump = menu.addAction('跳转到单词: {}'.format(item.word_text))
        action_jump.triggered.connect(lambda: self.word_double_clicked.emit(item.word_text))

        menu.exec_(self.mapToGlobal(pos))

    def _remove_association(self, node_a, node_b):
        """删除两个单词之间的关联
        :param node_a: WordNode A
        :param node_b: WordNode B
        """
        word_a = node_a.word_text
        word_b = node_b.word_text
        reply = QMessageBox.question(
            self, '确认删除',
            '确定要删除 "{}" 和 "{}" 之间的关联吗？'.format(word_a, word_b),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            # 从两个单词的associate集合中互相移除
            try:
                node_a.word_obj.associate.remove(word_b)
                node_b.word_obj.associate.remove(word_a)
            except KeyError:
                pass
            # 移除边
            for edge in self.scene.edges[:]:
                if (edge.source == node_a and edge.target == node_b) or \
                   (edge.source == node_b and edge.target == node_a):
                    self.scene.removeItem(edge)
                    self.scene.edges.remove(edge)
            # 更新邻居集合
            node_a.neighbors.discard(node_b)
            node_b.neighbors.discard(node_a)
            self.scene.highlight_neighbors(None)
            self.selected_node = None
            self.association_removed.emit(word_a, word_b)
            logger.info('已删除关联: {} <-> {}'.format(word_a, word_b))

    def filter_nodes(self, text):
        """过滤节点（供搜索框调用）"""
        self.scene.filter_by_text(text)

    def reset_view(self):
        """重置视图到初始位置和缩放"""
        self.resetTransform()
        self.fitInView(self.scene.itemsBoundingRect(), Qt.KeepAspectRatio)


class GraphPanelDialog(QDialog):
    """全局有向图面板对话框"""

    word_jump_requested = pyqtSignal(str)  # 请求跳转到指定单词
    graph_modified = pyqtSignal()          # 图被修改（删除关联等）

    def __init__(self, dictionary, parent=None):
        """
        初始化图面板对话框
        :param dictionary: Dictionary对象（词库）
        """
        super().__init__(parent)
        self.dictionary = dictionary
        self.setWindowTitle('单词关联图谱 - 全局有向图')
        self.resize(1000, 700)
        self._setup_ui()

    def _setup_ui(self):
        """设置UI布局"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # 顶部工具栏
        toolbar = QHBoxLayout()

        # 搜索框
        toolbar.addWidget(QLabel('搜索:'))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText('输入单词关键词搜索...')
        self.search_edit.textChanged.connect(self._on_search_changed)
        toolbar.addWidget(self.search_edit)

        # 掌握度筛选
        toolbar.addWidget(QLabel('掌握度:'))
        self.rank_combo = QComboBox()
        self.rank_combo.addItem('全部')
        for rank in ['精通', '掌握', '记住', '清晰', '模糊', '混淆', '忘记', '顽固', '待定']:
            self.rank_combo.addItem(rank)
        self.rank_combo.currentTextChanged.connect(self._on_rank_filter_changed)
        toolbar.addWidget(self.rank_combo)

        # 重置视图按钮
        self.reset_btn = QPushButton('重置视图')
        self.reset_btn.clicked.connect(self._reset_view)
        toolbar.addWidget(self.reset_btn)

        # 重新布局按钮
        self.relayout_btn = QPushButton('重新布局')
        self.relayout_btn.clicked.connect(self._relayout)
        toolbar.addWidget(self.relayout_btn)

        layout.addLayout(toolbar)

        # 图视图
        self.graph_view = GraphView()
        self.graph_view.word_double_clicked.connect(self._on_word_jump)
        self.graph_view.association_removed.connect(self._on_assoc_removed)
        layout.addWidget(self.graph_view)

        # 底部图例和提示
        legend_layout = QHBoxLayout()
        legend_layout.addWidget(QLabel('掌握度图例:'))
        for rank_name, color in RANK_COLORS.items():
            color_label = QLabel('●')
            color_label.setStyleSheet('color: rgb({},{},{})'.format(
                color.red(), color.green(), color.blue()))
            legend_layout.addWidget(color_label)
            legend_layout.addWidget(QLabel(rank_name))
        legend_layout.addStretch()

        hint_label = QLabel('提示: 单击高亮邻居 | 双击跳转单词 | 右键删除关联 | 滚轮缩放 | 拖拽平移')
        hint_label.setStyleSheet('color: gray;')
        legend_layout.addWidget(hint_label)
        layout.addLayout(legend_layout)

        # 加载图
        self.graph_view.load_dictionary(self.dictionary)

    def _on_search_changed(self, text):
        """搜索文本变化"""
        self.graph_view.filter_nodes(text)
        # 额外按掌握度筛选
        self._on_rank_filter_changed(self.rank_combo.currentText())

    def _on_rank_filter_changed(self, rank_text):
        """掌握度筛选变化"""
        for node in self.graph_view.scene.nodes.values():
            if rank_text == '全部' or node.get_rank() == rank_text:
                # 检查搜索文本过滤
                search_text = self.search_edit.text().strip().lower()
                if not search_text or search_text in node.word_text.lower():
                    node.setVisible(True)
                    node.label.setVisible(True)
                else:
                    node.setVisible(False)
                    node.label.setVisible(False)
            else:
                node.setVisible(False)
                node.label.setVisible(False)
        # 更新边的可见性
        for edge in self.graph_view.scene.edges:
            edge.setVisible(edge.source.isVisible() and edge.target.isVisible())

    def _reset_view(self):
        """重置视图"""
        self.search_edit.clear()
        self.rank_combo.setCurrentIndex(0)
        self.graph_view.reset_view()
        self.graph_view.filter_nodes('')

    def _relayout(self):
        """重新布局（重新启动力导向模拟）"""
        self.graph_view.refresh_colors()
        self.graph_view.scene.start_simulation()

    def _on_word_jump(self, word_text):
        """单词双击跳转"""
        self.word_jump_requested.emit(word_text)
        self.accept()  # 关闭对话框

    def _on_assoc_removed(self, word_a, word_b):
        """关联被删除"""
        self.graph_modified.emit()

    def refresh(self):
        """刷新图（词库变化后调用）"""
        self.graph_view.load_dictionary(self.dictionary)
