# -*- coding: utf-8 -*-
# @File    : GraphPanel.py
# @Desc    : 全局单词关联有向图面板。
#
# 需求 1:将"单次添加关联词"升级为"全局有向图面板(QGraphicsView)"。
#   - 以力导向布局(Fruchterman-Reingold)展示所有含关联关系的单词节点;
#   - 节点按掌握度(rank)着色;
#   - 单击节点:高亮其邻居(其余淡出);
#   - 双击节点:视图聚焦并放大到该节点(跳转);
#   - 右键点击边:删除该条关联关系;
#   - 顶部搜索框:按单词文本过滤高亮;
#   - 支持鼠标滚轮缩放、拖拽平移。
#
# 关联关系是有向的:Vocabulary.associate 中的每个词都是 "本词 -> 关联词"。
import math
import random

from PyQt5.QtCore import Qt, QRectF, QPointF, QLineF, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QPen, QBrush, QPainter, QPainterPath, QFont, QPolygonF
from PyQt5.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsItem, QGraphicsEllipseItem,
    QGraphicsPathItem, QGraphicsSimpleTextItem, QWidget, QVBoxLayout,
    QHBoxLayout, QLineEdit, QLabel, QPushButton, QMenu, QMessageBox,
)

from SmartReview.Base import Dictionary
from SmartReview import Palette


# ----------------------------------------------------------------------------
#  图元:节点
# ----------------------------------------------------------------------------
class NodeItem(QGraphicsEllipseItem):
    """ 代表一个单词的圆形节点 """

    RADIUS = 16  # 节点半径

    def __init__(self, word, rank, view):
        super(NodeItem, self).__init__(-self.RADIUS, -self.RADIUS,
                                       self.RADIUS * 2, self.RADIUS * 2)
        self.word = word            # 单词字符串
        self.rank = rank            # 掌握程度
        self._view = view           # 反向引用面板,便于交互回调
        # 力导向布局用到的物理量
        self.vx = 0.0
        self.vy = 0.0

        self.setZValue(2)  # 节点显示在边之上
        self.setFlag(QGraphicsItem.ItemIsMovable, True)      # 允许手动拖拽节点
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.PointingHandCursor)
        self._apply_color()

        # 节点下方的单词文字
        self.label = QGraphicsSimpleTextItem(word, self)
        font = QFont()
        font.setPointSize(9)
        self.label.setFont(font)
        rect = self.label.boundingRect()
        self.label.setPos(-rect.width() / 2, self.RADIUS + 2)  # 居中放在圆下方
        self.label.setZValue(3)

    def _apply_color(self, dim=False):
        """ 根据掌握度上色;dim=True 时淡化(用于高亮邻居时使非邻居变淡) """
        color = QColor(Palette.color_of(self.rank))
        if dim:
            color.setAlpha(45)
        self.setBrush(QBrush(color))
        pen = QPen(QColor('#37474F'))
        pen.setWidthF(1.5)
        if dim:
            pen.setColor(QColor(55, 71, 79, 45))
        self.setPen(pen)

    def set_dim(self, dim):
        """ 设置淡化状态,并同步文字透明度 """
        self._apply_color(dim)
        self.label.setOpacity(0.25 if dim else 1.0)

    def itemChange(self, change, value):
        # 节点位置变化时,通知面板刷新与之相连的边
        if change == QGraphicsItem.ItemPositionHasChanged and self._view is not None:
            self._view.update_edges_of(self.word)
        return super(NodeItem, self).itemChange(change, value)

    def mousePressEvent(self, event):
        # 单击:高亮邻居
        if event.button() == Qt.LeftButton and self._view is not None:
            self._view.highlight_neighbors(self.word)
        super(NodeItem, self).mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        # 双击:聚焦跳转到该节点
        if self._view is not None:
            self._view.focus_on(self.word)
        super(NodeItem, self).mouseDoubleClickEvent(event)


# ----------------------------------------------------------------------------
#  图元:有向边(带箭头)
# ----------------------------------------------------------------------------
class EdgeItem(QGraphicsPathItem):
    """ 代表 source -> target 的一条有向关联边 """

    def __init__(self, source_word, target_word, view):
        super(EdgeItem, self).__init__()
        self.source_word = source_word
        self.target_word = target_word
        self._view = view
        self.setZValue(1)  # 边在节点之下
        self.setPen(QPen(QColor('#B0BEC5'), 1.6))
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.PointingHandCursor)

    def set_dim(self, dim):
        """ 高亮邻居时,非相关边淡化 """
        color = QColor('#B0BEC5')
        if dim:
            color.setAlpha(35)
        self.setPen(QPen(color, 1.6))

    def set_highlight(self, on):
        """ 高亮显示这条边(选中节点的关联边) """
        color = QColor('#FF7043') if on else QColor('#B0BEC5')
        self.setPen(QPen(color, 2.4 if on else 1.6))

    def update_path(self, p1, p2):
        """ 依据两端节点坐标,重新绘制这条带箭头的边 """
        path = QPainterPath()
        # 让线段止于目标节点圆周外侧,避免箭头戳进圆里
        line = QLineF(p1, p2)
        length = line.length()
        if length < 1e-6:
            self.setPath(path)
            return
        # 单位方向向量
        ux = (p2.x() - p1.x()) / length
        uy = (p2.y() - p1.y()) / length
        start = QPointF(p1.x() + ux * NodeItem.RADIUS, p1.y() + uy * NodeItem.RADIUS)
        end = QPointF(p2.x() - ux * NodeItem.RADIUS, p2.y() - uy * NodeItem.RADIUS)
        path.moveTo(start)
        path.lineTo(end)
        # 箭头(两条短边)
        arrow_size = 8.0
        angle = math.atan2(end.y() - start.y(), end.x() - start.x())
        a1 = QPointF(end.x() - arrow_size * math.cos(angle - math.pi / 6),
                     end.y() - arrow_size * math.sin(angle - math.pi / 6))
        a2 = QPointF(end.x() - arrow_size * math.cos(angle + math.pi / 6),
                     end.y() - arrow_size * math.sin(angle + math.pi / 6))
        arrow = QPolygonF([end, a1, a2])
        path.addPolygon(arrow)
        self.setPath(path)

    def contextMenuEvent(self, event):
        # 右键:删除这条关联关系
        if self._view is not None:
            self._view.request_delete_edge(self)
        event.accept()


# ----------------------------------------------------------------------------
#  视图:力导向图
# ----------------------------------------------------------------------------
class GraphView(QGraphicsView):
    """ 承载节点与边的画布,负责力导向迭代、缩放、平移与交互 """

    # 双击节点跳转时对外发出的信号(把单词传给主窗口)
    nodeActivated = pyqtSignal(str)

    def __init__(self, parent=None):
        super(GraphView, self).__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.ScrollHandDrag)   # 空白处拖拽平移
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)  # 以鼠标为锚点缩放

        self.book = None
        self.nodes = {}   # word -> NodeItem
        self.edges = []   # [EdgeItem, ...]
        self._selected = None  # 当前高亮的中心节点

        # 力导向布局迭代定时器
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._step_layout)
        self._iterations_left = 0

    # ---------------- 数据装载 ----------------
    def load_book(self, book):
        """ 从词书构建关联图:只纳入"有关联关系"的单词及其关联目标 """
        assert isinstance(book, Dictionary)
        self.book = book
        self._scene.clear()
        self.nodes.clear()
        self.edges.clear()
        self._selected = None

        # 收集所有参与关联的单词(源词 + 目标词)
        involved = set()
        pairs = []  # (source, target)
        for word_obj in book.values():
            if word_obj.associate:
                for target in word_obj.associate:
                    involved.add(word_obj.value)
                    involved.add(target)
                    pairs.append((word_obj.value, target))

        # 创建节点,随机初始散布在一个圆内,给力导向一个起点
        for word in involved:
            rank = book[word].rank if word in book.data else '待定'
            node = NodeItem(word, rank, self)
            angle = random.uniform(0, 2 * math.pi)
            radius = random.uniform(0, 300)
            node.setPos(math.cos(angle) * radius, math.sin(angle) * radius)
            self._scene.addItem(node)
            self.nodes[word] = node

        # 创建有向边
        for src, dst in pairs:
            if src in self.nodes and dst in self.nodes:
                edge = EdgeItem(src, dst, self)
                self._scene.addItem(edge)
                self.edges.append(edge)

        self._refresh_all_edges()
        self.start_layout()
        return len(self.nodes), len(self.edges)

    # ---------------- 力导向布局 ----------------
    def start_layout(self, iterations=300):
        """ 启动力导向迭代动画 """
        if not self.nodes:
            return
        self._iterations_left = iterations
        self._timer.start(16)  # ~60fps

    def _step_layout(self):
        """ 单步 Fruchterman-Reingold:斥力(全体)+ 引力(相连) """
        if self._iterations_left <= 0 or not self.nodes:
            self._timer.stop()
            self.fit_all()
            return

        nodes = list(self.nodes.values())
        area = 900.0 * 900.0
        k = math.sqrt(area / max(len(nodes), 1))  # 理想边长
        # 计算斥力
        for a in nodes:
            a.vx = 0.0
            a.vy = 0.0
        for i, a in enumerate(nodes):
            for b in nodes[i + 1:]:
                dx = a.x() - b.x()
                dy = a.y() - b.y()
                dist = math.hypot(dx, dy) or 0.01
                force = (k * k) / dist       # 斥力与距离成反比
                fx = dx / dist * force
                fy = dy / dist * force
                a.vx += fx; a.vy += fy
                b.vx -= fx; b.vy -= fy
        # 计算引力(仅相连节点)
        for edge in self.edges:
            a = self.nodes[edge.source_word]
            b = self.nodes[edge.target_word]
            dx = a.x() - b.x()
            dy = a.y() - b.y()
            dist = math.hypot(dx, dy) or 0.01
            force = (dist * dist) / k        # 引力与距离平方成正比
            fx = dx / dist * force
            fy = dy / dist * force
            a.vx -= fx; a.vy -= fy
            b.vx += fx; b.vy += fy

        # 应用位移(限幅,避免抖动)并逐步降温
        temp = 8.0
        for n in nodes:
            disp = math.hypot(n.vx, n.vy) or 0.01
            limited = min(disp, temp)
            # setPos 会触发 itemChange 从而刷新边
            n.setPos(n.x() + n.vx / disp * limited,
                     n.y() + n.vy / disp * limited)

        self._iterations_left -= 1

    # ---------------- 边刷新 ----------------
    def _refresh_all_edges(self):
        for edge in self.edges:
            self._update_single_edge(edge)

    def _update_single_edge(self, edge):
        src = self.nodes.get(edge.source_word)
        dst = self.nodes.get(edge.target_word)
        if src and dst:
            edge.update_path(src.pos(), dst.pos())

    def update_edges_of(self, word):
        """ 某个节点被移动后,刷新与之相连的所有边 """
        for edge in self.edges:
            if edge.source_word == word or edge.target_word == word:
                self._update_single_edge(edge)

    # ---------------- 交互:高亮邻居 ----------------
    def highlight_neighbors(self, word):
        """ 单击节点:高亮该节点及其直接邻居,其余淡出 """
        if self._selected == word:
            # 再次点击同一节点则取消高亮
            self.clear_highlight()
            return
        self._selected = word
        # 找出邻居(出边 + 入边)
        neighbors = {word}
        related_edges = set()
        for i, edge in enumerate(self.edges):
            if edge.source_word == word:
                neighbors.add(edge.target_word)
                related_edges.add(i)
            elif edge.target_word == word:
                neighbors.add(edge.source_word)
                related_edges.add(i)
        # 应用淡化 / 高亮
        for w, node in self.nodes.items():
            node.set_dim(w not in neighbors)
        for i, edge in enumerate(self.edges):
            if i in related_edges:
                edge.set_dim(False)
                edge.set_highlight(True)
            else:
                edge.set_dim(True)

    def clear_highlight(self):
        """ 取消所有高亮 / 淡化 """
        self._selected = None
        for node in self.nodes.values():
            node.set_dim(False)
        for edge in self.edges:
            edge.set_dim(False)
            edge.set_highlight(False)

    # ---------------- 交互:双击跳转 ----------------
    def focus_on(self, word):
        """ 双击节点:居中放大到该节点,并对外广播 """
        node = self.nodes.get(word)
        if node is None:
            return
        self.highlight_neighbors(word)
        self.centerOn(node)
        # 适度放大
        self.resetTransform()
        self.scale(1.6, 1.6)
        self.centerOn(node)
        self.nodeActivated.emit(word)

    # ---------------- 交互:删除边 ----------------
    def request_delete_edge(self, edge):
        """ 右键删除关联:同时修改底层数据 associate 集合 """
        reply = QMessageBox.question(
            self, '删除关联',
            '确定要删除关联: {} → {} 吗?'.format(edge.source_word, edge.target_word),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        # 更新数据模型
        src_obj = self.book.data.get(edge.source_word) if self.book else None
        if src_obj is not None and edge.target_word in src_obj.associate:
            src_obj.associate.remove(edge.target_word)
        # 从场景中移除
        self._scene.removeItem(edge)
        if edge in self.edges:
            self.edges.remove(edge)
        # 清理不再有任何连接的孤立节点
        self._prune_isolated_nodes()

    def _prune_isolated_nodes(self):
        """ 删除没有任何边相连的孤立节点 """
        connected = set()
        for edge in self.edges:
            connected.add(edge.source_word)
            connected.add(edge.target_word)
        for word in list(self.nodes.keys()):
            if word not in connected:
                self._scene.removeItem(self.nodes[word])
                del self.nodes[word]

    # ---------------- 交互:搜索过滤 ----------------
    def filter_by_text(self, text):
        """ 顶部搜索:匹配到的节点保持醒目,其余淡出 """
        text = text.strip().lower()
        if not text:
            self.clear_highlight()
            return
        matched = {w for w in self.nodes if text in w.lower()}
        for w, node in self.nodes.items():
            node.set_dim(w not in matched)
        for edge in self.edges:
            edge.set_dim(True)
        # 若只匹配到一个,顺便聚焦过去
        if len(matched) == 1:
            self.centerOn(self.nodes[next(iter(matched))])

    # ---------------- 缩放 / 适配 ----------------
    def wheelEvent(self, event):
        """ 滚轮缩放 """
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)

    def fit_all(self):
        """ 缩放到能看到全部节点 """
        if self.nodes:
            rect = self._scene.itemsBoundingRect()
            rect.adjust(-40, -40, 40, 40)
            self.fitInView(rect, Qt.KeepAspectRatio)


# ----------------------------------------------------------------------------
#  面板:搜索栏 + 工具按钮 + 图视图
# ----------------------------------------------------------------------------
class GraphPanel(QWidget):
    """ 关联有向图窗口:顶部工具栏 + 中央 GraphView """

    def __init__(self, book, mainwindow=None, parent=None):
        super(GraphPanel, self).__init__(parent)
        self.book = book
        self.mainwindow = mainwindow
        self.setWindowTitle('单词关联有向图')
        self.resize(900, 640)

        layout = QVBoxLayout(self)

        # 顶部工具栏:搜索 + 操作按钮
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel('搜索:'))
        self.searchEdit = QLineEdit()
        self.searchEdit.setPlaceholderText('输入单词过滤高亮…')
        toolbar.addWidget(self.searchEdit)
        self.fitButton = QPushButton('适配全部')
        self.relayoutButton = QPushButton('重新布局')
        self.resetButton = QPushButton('取消高亮')
        toolbar.addWidget(self.fitButton)
        toolbar.addWidget(self.relayoutButton)
        toolbar.addWidget(self.resetButton)
        layout.addLayout(toolbar)

        # 图视图
        self.view = GraphView(self)
        layout.addWidget(self.view)

        # 底部状态栏
        self.statusLabel = QLabel('')
        layout.addWidget(self.statusLabel)

        # 信号槽
        self.searchEdit.textChanged.connect(self.view.filter_by_text)
        self.fitButton.clicked.connect(self.view.fit_all)
        self.relayoutButton.clicked.connect(lambda: self.view.start_layout())
        self.resetButton.clicked.connect(self.view.clear_highlight)
        self.view.nodeActivated.connect(self._on_node_activated)

    def show(self):
        """ 每次显示都基于最新数据重建图 """
        n_nodes, n_edges = self.view.load_book(self.book)
        self.statusLabel.setText('共 {} 个关联节点, {} 条关联边。'
                                 '单击高亮邻居 / 双击聚焦 / 右键删除关联。'
                                 .format(n_nodes, n_edges))
        super(GraphPanel, self).show()
        self.raise_()
        self.activateWindow()

    def _on_node_activated(self, word):
        """ 双击节点时的回调:可用于联动主窗口(此处更新状态提示) """
        self.statusLabel.setText('已聚焦到: {}'.format(word))
