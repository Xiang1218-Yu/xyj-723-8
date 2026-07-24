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

# 力导向模拟的节点数阈值：超过此数量使用网格布局而非物理模拟
MAX_FORCE_NODES = 150


class WordNode(QGraphicsEllipseItem):
    """单词节点类 - 在力导向图中表示一个单词"""

    def __init__(self, word_obj, radius=20, parent=None):
        super().__init__(-radius, -radius, radius * 2, radius * 2, parent)
        self.word_obj = word_obj
        self.word_text = word_obj.value
        self.radius = radius

        # 力导向模拟相关属性
        self.vel = QPointF(0, 0)
        self.pos = QPointF(0, 0)
        self.force = QPointF(0, 0)

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
        text_rect = self.label.boundingRect()
        self.label.setPos(-text_rect.width() / 2, radius + 2)
        self.label.setZValue(11)

        # 高亮状态
        self.highlighted = False
        self.neighbors = set()

    def _get_color(self):
        rank = self.word_obj.rank
        return RANK_COLORS.get(rank, RANK_COLORS['待定'])

    def update_color(self):
        self.setBrush(QBrush(self._get_color()))

    def get_rank(self):
        return self.word_obj.rank

    def set_highlight(self, highlight, is_neighbor=False):
        self.highlighted = highlight
        if highlight:
            if is_neighbor:
                self.setPen(QPen(QColor(26, 188, 156), 4))
                self.setScale(1.15)
            else:
                self.setPen(QPen(QColor(241, 196, 15), 5))
                self.setScale(1.3)
            self.setZValue(20)
        else:
            self.setPen(QPen(QColor(255, 255, 255), 2))
            self.setScale(1.0)
            self.setZValue(10)

    def apply_force(self, force_x, force_y):
        self.force += QPointF(force_x, force_y)

    def step(self, damping=0.85, max_speed=15.0):
        self.vel = (self.vel + self.force) * damping
        speed = math.hypot(self.vel.x(), self.vel.y())
        if speed > max_speed:
            self.vel *= max_speed / speed
        self.pos += self.vel
        self.setPos(self.pos)
        self.force = QPointF(0, 0)


class EdgeLine(QGraphicsLineItem):
    """边/关联线类 - 表示两个单词之间的关联关系"""

    def __init__(self, source_node, target_node, parent=None):
        super().__init__(parent)
        self.source = source_node
        self.target = target_node
        self.setPen(QPen(QColor(180, 180, 180, 120), 1.5))
        self.setZValue(1)
        self.highlighted = False
        self._update_position()

    def _update_position(self):
        if self.source and self.target:
            self.setLine(
                self.source.pos().x(), self.source.pos().y(),
                self.target.pos().x(), self.target.pos().y()
            )

    def set_highlight(self, highlight):
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
    REPULSION = 5000
    ATTRACTION = 0.008
    DAMPING = 0.85
    MAX_SPEED = 10.0
    CENTER_GRAVITY = 0.003
    IDEAL_DISTANCE = 120
    SIMULATION_STEPS = 2
    MAX_SIM_ITERATIONS = 200  # 最大模拟迭代次数，防止无限运行

    def __init__(self, parent=None):
        super().__init__(parent)
        self.nodes = {}
        self.edges = []
        self.timer = QTimer()
        self.timer.timeout.connect(self._simulate_step)
        self.is_simulating = False
        self.temperature = 1.0
        self.iteration_count = 0

    def _grid_layout(self, words):
        """网格布局 - 用于大量节点时的快速布局
        :param words: Vocabulary对象列表
        :return: word_text -> QPointF 位置映射
        """
        n = len(words)
        # 计算合适的列数（大致正方形）
        cols = int(math.ceil(math.sqrt(n)))
        spacing = 55  # 节点间距
        positions = {}
        for i, word_obj in enumerate(words):
            row = i // cols
            col = i % cols
            x = (col - cols / 2) * spacing
            y = (row - (n / cols) / 2) * spacing
            positions[word_obj.value] = QPointF(x, y)
        return positions

    def build_graph(self, dictionary):
        """从Dictionary对象构建图
        :param dictionary: Dictionary对象（词库）
        """
        self.stop_simulation()
        self.clear_all()

        words = list(dictionary.values())
        if not words:
            return

        n_nodes = len(words)
        use_force = n_nodes <= MAX_FORCE_NODES

        # 决定初始位置：小图用力导向随机布局，大图用网格布局
        if use_force:
            positions = {}
            center = QPointF(0, 0)
            for word_obj in words:
                angle = random.uniform(0, 2 * math.pi)
                dist = random.uniform(50, 200)
                positions[word_obj.value] = QPointF(
                    center.x() + math.cos(angle) * dist,
                    center.y() + math.sin(angle) * dist
                )
        else:
            positions = self._grid_layout(words)

        # 创建节点
        for word_obj in words:
            node = WordNode(word_obj)
            node.pos = positions.get(word_obj.value, QPointF(0, 0))
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
                if target_node and assoc_text > word_obj.value:
                    edge = EdgeLine(source_node, target_node)
                    self.addItem(edge)
                    self.edges.append(edge)
                    source_node.neighbors.add(target_node)
                    target_node.neighbors.add(source_node)

        # 设置场景大小
        if self.nodes:
            all_positions = [n.pos for n in self.nodes.values()]
            min_x = min(p.x() for p in all_positions) - 80
            max_x = max(p.x() for p in all_positions) + 80
            min_y = min(p.y() for p in all_positions) - 80
            max_y = max(p.y() for p in all_positions) + 80
            self.setSceneRect(min_x, min_y, max_x - min_x, max_y - min_y)
        else:
            self.setSceneRect(-500, -500, 1000, 1000)

        # 小图启用力导向模拟
        if use_force:
            self.start_simulation()

    def clear_all(self):
        self.nodes.clear()
        self.edges.clear()
        self.clear()

    def start_simulation(self):
        """启动力导向模拟（有限迭代次数）"""
        self.temperature = 1.0
        self.iteration_count = 0
        self.is_simulating = True
        self.timer.start(25)

    def stop_simulation(self):
        self.is_simulating = False
        self.timer.stop()

    def _simulate_step(self):
        """执行一步物理模拟（带迭代计数上限保护）"""
        if not self.is_simulating:
            return

        for _ in range(self.SIMULATION_STEPS):
            self.iteration_count += 1
            self.temperature *= 0.992

            # 停止条件：温度过低或达到最大迭代次数
            if self.temperature < 0.03 or self.iteration_count > self.MAX_SIM_ITERATIONS:
                self.stop_simulation()
                break

            node_list = list(self.nodes.values())

            # 计算斥力（节点之间） - O(n²)，仅用于小规模图
            for i, n1 in enumerate(node_list):
                for n2 in node_list[i + 1:]:
                    delta = n1.pos - n2.pos
                    dist_sq = delta.x() ** 2 + delta.y() ** 2
                    if dist_sq < 1:
                        dist_sq = 1
                    # 超过一定距离的节点斥力忽略不计，减少计算
                    if dist_sq > 50000:
                        continue
                    dist = math.sqrt(dist_sq)
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
        """高亮选中节点及其邻居"""
        for node in self.nodes.values():
            node.set_highlight(False)
        for edge in self.edges:
            edge.set_highlight(False)

        if selected_node is None:
            return

        selected_node.set_highlight(True)
        for edge in self.edges:
            if edge.source == selected_node:
                edge.target.set_highlight(True, is_neighbor=True)
                edge.set_highlight(True)
            elif edge.target == selected_node:
                edge.source.set_highlight(True, is_neighbor=True)
                edge.set_highlight(True)

    def filter_by_text(self, filter_text):
        """根据搜索文本过滤节点"""
        filter_text = filter_text.strip().lower()
        for text, node in self.nodes.items():
            if not filter_text or filter_text in text.lower():
                node.setVisible(True)
                node.label.setVisible(True)
            else:
                node.setVisible(False)
                node.label.setVisible(False)
        for edge in self.edges:
            edge.setVisible(edge.source.isVisible() and edge.target.isVisible())


class GraphView(QGraphicsView):
    """力导向图视图 - 支持缩放平移和交互"""

    word_double_clicked = pyqtSignal(str)
    association_removed = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene = ForceDirectedScene()
        self.setScene(self.scene)

        self.setRenderHint(QPainter.Antialiasing)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setBackgroundBrush(QBrush(QColor(250, 250, 250)))

        self.selected_node = None
        self._pending_fit = False

        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    def load_dictionary(self, dictionary):
        """加载词库并构建图（fitInView延迟到show后执行）"""
        self.scene.build_graph(dictionary)
        self._pending_fit = True

    def showEvent(self, event):
        """视图显示后执行fitInView，避免构造时尺寸为0的问题"""
        super().showEvent(event)
        if self._pending_fit and self.scene.itemsBoundingRect().isValid():
            self.fitInView(self.scene.itemsBoundingRect().adjusted(-20, -20, 20, 20), Qt.KeepAspectRatio)
            self._pending_fit = False

    def refresh_colors(self):
        for node in self.scene.nodes.values():
            node.update_color()

    def wheelEvent(self, event):
        zoom_factor = 1.15
        if event.angleDelta().y() > 0:
            self.scale(zoom_factor, zoom_factor)
        else:
            self.scale(1 / zoom_factor, 1 / zoom_factor)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            item = self.itemAt(event.pos())
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
        if event.button() == Qt.LeftButton:
            item = self.itemAt(event.pos())
            if isinstance(item, QGraphicsTextItem) and item.parentItem():
                item = item.parentItem()
            if isinstance(item, WordNode):
                self.word_double_clicked.emit(item.word_text)
        super().mouseDoubleClickEvent(event)

    def _show_context_menu(self, pos):
        item = self.itemAt(pos)
        if isinstance(item, QGraphicsTextItem) and item.parentItem():
            item = item.parentItem()
        if not isinstance(item, WordNode):
            return

        menu = QMenu(self)

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
        word_a = node_a.word_text
        word_b = node_b.word_text
        reply = QMessageBox.question(
            self, '确认删除',
            '确定要删除 "{}" 和 "{}" 之间的关联吗？'.format(word_a, word_b),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            node_a.word_obj.associate.discard(word_b)
            node_b.word_obj.associate.discard(word_a)
            for edge in self.scene.edges[:]:
                if (edge.source == node_a and edge.target == node_b) or \
                   (edge.source == node_b and edge.target == node_a):
                    self.scene.removeItem(edge)
                    self.scene.edges.remove(edge)
            node_a.neighbors.discard(node_b)
            node_b.neighbors.discard(node_a)
            self.scene.highlight_neighbors(None)
            self.selected_node = None
            self.association_removed.emit(word_a, word_b)
            logger.info('已删除关联: {} <-> {}'.format(word_a, word_b))

    def filter_nodes(self, text):
        self.scene.filter_by_text(text)

    def reset_view(self):
        self.resetTransform()
        rect = self.scene.itemsBoundingRect()
        if rect.isValid():
            self.fitInView(rect.adjusted(-20, -20, 20, 20), Qt.KeepAspectRatio)


class GraphPanelDialog(QDialog):
    """全局有向图面板对话框"""

    word_jump_requested = pyqtSignal(str)
    graph_modified = pyqtSignal()

    def __init__(self, dictionary, parent=None):
        super().__init__(parent)
        self.dictionary = dictionary
        self.setWindowTitle('单词关联图谱 - 全局有向图')
        self.resize(1000, 700)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # 顶部工具栏
        toolbar = QHBoxLayout()

        toolbar.addWidget(QLabel('搜索:'))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText('输入单词关键词搜索...')
        self.search_edit.textChanged.connect(self._on_search_changed)
        toolbar.addWidget(self.search_edit)

        toolbar.addWidget(QLabel('掌握度:'))
        self.rank_combo = QComboBox()
        self.rank_combo.addItem('全部')
        for rank in ['精通', '掌握', '记住', '清晰', '模糊', '混淆', '忘记', '顽固', '待定']:
            self.rank_combo.addItem(rank)
        self.rank_combo.currentTextChanged.connect(self._on_rank_filter_changed)
        toolbar.addWidget(self.rank_combo)

        self.reset_btn = QPushButton('重置视图')
        self.reset_btn.clicked.connect(self._reset_view)
        toolbar.addWidget(self.reset_btn)

        self.relayout_btn = QPushButton('重新布局')
        self.relayout_btn.clicked.connect(self._relayout)
        toolbar.addWidget(self.relayout_btn)

        layout.addLayout(toolbar)

        # 节点计数提示
        n_words = len(self.dictionary)
        if n_words > MAX_FORCE_NODES:
            info_label = QLabel(
                '💡 当前 {} 个单词，已使用网格布局（节点数 >{} 时自动切换，可点击"重新布局"尝试力导向）'.format(
                    n_words, MAX_FORCE_NODES)
            )
            info_label.setStyleSheet('color: #666; font-size: 11px;')
            layout.addWidget(info_label)

        self.graph_view = GraphView()
        self.graph_view.word_double_clicked.connect(self._on_word_jump)
        self.graph_view.association_removed.connect(self._on_assoc_removed)
        layout.addWidget(self.graph_view)

        # 底部图例
        legend_layout = QHBoxLayout()
        legend_layout.addWidget(QLabel('掌握度图例:'))
        for rank_name, color in RANK_COLORS.items():
            color_label = QLabel('●')
            color_label.setStyleSheet('color: rgb({},{},{})'.format(
                color.red(), color.green(), color.blue()))
            legend_layout.addWidget(color_label)
            legend_layout.addWidget(QLabel(rank_name))
        legend_layout.addStretch()

        hint_label = QLabel('提示: 单击高亮邻居 | 双击跳转 | 右键删关联 | 滚轮缩放 | 拖拽平移')
        hint_label.setStyleSheet('color: gray;')
        legend_layout.addWidget(hint_label)
        layout.addLayout(legend_layout)

        self.graph_view.load_dictionary(self.dictionary)

    def _on_search_changed(self, text):
        self.graph_view.filter_nodes(text)
        self._on_rank_filter_changed(self.rank_combo.currentText())

    def _on_rank_filter_changed(self, rank_text):
        for node in self.graph_view.scene.nodes.values():
            if rank_text == '全部' or node.get_rank() == rank_text:
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
        for edge in self.graph_view.scene.edges:
            edge.setVisible(edge.source.isVisible() and edge.target.isVisible())

    def _reset_view(self):
        self.search_edit.clear()
        self.rank_combo.setCurrentIndex(0)
        self.graph_view.reset_view()
        self.graph_view.filter_nodes('')

    def _relayout(self):
        """重新布局 - 强制运行力导向模拟（无论节点数）"""
        self.graph_view.refresh_colors()
        # 重新构建图以力导向方式布局（临时降低阈值）
        self.graph_view.scene.stop_simulation()
        words = list(self.dictionary.values())
        if words:
            # 随机打乱位置后启动模拟
            import random as _r
            center = QPointF(0, 0)
            for node in self.graph_view.scene.nodes.values():
                angle = _r.uniform(0, 2 * math.pi)
                dist = _r.uniform(50, 250)
                node.pos = QPointF(
                    center.x() + math.cos(angle) * dist,
                    center.y() + math.sin(angle) * dist
                )
                node.setPos(node.pos)
                node.vel = QPointF(0, 0)
            self.graph_view.scene.start_simulation()

    def _on_word_jump(self, word_text):
        self.word_jump_requested.emit(word_text)
        self.accept()

    def _on_assoc_removed(self, word_a, word_b):
        self.graph_modified.emit()

    def refresh(self):
        self.graph_view.load_dictionary(self.dictionary)
