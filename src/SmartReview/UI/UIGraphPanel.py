# -*- coding: utf-8 -*-
# @File    : UIGraphPanel.py
# @说明    : 全局关联有向图面板: 力导向布局 + 节点按掌握度着色 + 点击高亮/双击跳转/右键删边 + 搜索过滤/缩放平移
import math
import random
import logging

from PyQt5.QtCore import Qt, QPointF, QRectF, pyqtSignal, QTimer
from PyQt5.QtGui import QColor, QBrush, QPen, QPainter, QPainterPath, QFont, QPolygonF
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, QLabel,
    QGraphicsView, QGraphicsScene, QGraphicsEllipseItem, QGraphicsTextItem,
    QGraphicsLineItem, QGraphicsPathItem, QGraphicsItem, QMenu, QAction,
    QGraphicsSceneMouseEvent, QMessageBox, QCheckBox, QSpinBox, QSizePolicy
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 掌握度 -> 颜色映射(与 Vocabulary.rank_table 对应)
# ---------------------------------------------------------------------------
RANK_COLORS = {
    '精通': QColor('#2ecc71'),  # 绿色
    '掌握': QColor('#27ae60'),
    '记住': QColor('#3498db'),  # 蓝色
    '清晰': QColor('#5dade2'),
    '模糊': QColor('#f1c40f'),  # 黄色
    '混淆': QColor('#e67e22'),  # 橙色
    '忘记': QColor('#e74c3c'),  # 红色
    '顽固': QColor('#8e44ad'),  # 紫色
    '待定': QColor('#95a5a6'),  # 灰色
}


class GraphNode(QGraphicsEllipseItem):
    """ 图节点: 圆形 + 单词文本 """

    def __init__(self, word_obj, panel):
        # 圆形半径: 有关联词的节点稍大,强化视觉中心
        self.word_obj = word_obj
        self.panel = panel  # 父面板引用,用于事件回调
        has_assoc = len(getattr(word_obj, 'associate', [])) > 0
        self.radius = 22 if has_assoc else 16
        super().__init__(-self.radius, -self.radius, self.radius * 2, self.radius * 2)

        # 视觉样式
        self.setBrush(QBrush(self._color()))
        self.setPen(QPen(QColor('#34495e'), 1.2))
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemIsFocusable, True)
        self.setAcceptHoverEvents(True)
        self.setToolTip('{}\n{}'.format(word_obj.value, word_obj.explain.replace('\n', ' ')[:120]))

        # 力导向布局中使用的位移/速度
        self.vel = QPointF(0, 0)

        # 节点上的文本标签
        self.text_item = QGraphicsTextItem(word_obj.value, self)
        f = QFont()
        f.setPointSize(8 if has_assoc else 7)
        self.text_item.setFont(f)
        self.text_item.setDefaultTextColor(QColor('#2c3e50'))
        # 文本居中放在圆下方
        br = self.text_item.boundingRect()
        self.text_item.setPos(-br.width() / 2, self.radius + 2)

    def _color(self):
        rank = getattr(self.word_obj, 'rank', '待定')
        return RANK_COLORS.get(rank, QColor('#95a5a6'))

    def refresh_color(self):
        """ 当单词掌握度变化时刷新颜色 """
        self.setBrush(QBrush(self._color()))

    # -- 鼠标事件 ----------------------------------------------------------------
    def mousePressEvent(self, event: QGraphicsSceneMouseEvent):
        if event.button() == Qt.LeftButton:
            self.panel.highlight_neighbors(self.word_obj.value)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QGraphicsSceneMouseEvent):
        # 双击跳转到该单词: 发射信号给主窗口
        self.panel.jump_to_word.emit(self.word_obj.value)
        super().mouseDoubleClickEvent(event)

    def hoverEnterEvent(self, event):
        self.setScale(1.25)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.setScale(1.0)
        super().hoverLeaveEvent(event)


class GraphEdge(QGraphicsPathItem):
    """ 有向边: 带箭头, 支持右键删除 """

    def __init__(self, src: GraphNode, dst: GraphNode, panel):
        super().__init__()
        self.src = src
        self.dst = dst
        self.panel = panel
        self.setPen(QPen(QColor('#7f8c8d'), 1.2))
        self.setZValue(-1)
        self.setFlag(QGraphicsItem.ItemIsSelectable, False)
        self._arrow_head = None  # 箭头多边形
        self.update_path()

    def update_path(self):
        """ 更新边的轨迹,箭头指向 dst 圆的边缘 """
        p1 = self.src.pos()
        p2 = self.dst.pos()
        # 计算从 src 中心到 dst 边缘的交点,避免箭头插入圆内
        d = math.hypot(p2.x() - p1.x(), p2.y() - p1.y()) or 0.001
        ux, uy = (p2.x() - p1.x()) / d, (p2.y() - p1.y()) / d
        start = QPointF(p1.x() + ux * self.src.radius, p1.y() + uy * self.src.radius)
        end = QPointF(p2.x() - ux * self.dst.radius, p2.y() - uy * self.dst.radius)
        path = QPainterPath(start)
        path.lineTo(end)
        self.setPath(path)

    def contextMenuEvent(self, event):
        """ 右键删除关联 """
        menu = QMenu()
        act_del = QAction('删除关联: {} -> {}'.format(self.src.word_obj.value, self.dst.word_obj.value), menu)
        menu.addAction(act_del)
        chosen = menu.exec_(event.screenPos())
        if chosen is act_del:
            self.panel.remove_association(self.src.word_obj.value, self.dst.word_obj.value)


class AssociationsGraphView(QGraphicsView):
    """ 支持缩放(Ctrl+滚轮) 与平移(空白处拖拽) 的 QGraphicsView """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.ScrollHandDrag)  # 默认空白处拖动手型平移
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self._panning = False

    def wheelEvent(self, event):
        # Ctrl+滚轮缩放, 否则默认滚动
        if event.modifiers() & Qt.ControlModifier:
            factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
            self.scale(factor, factor)
        else:
            super().wheelEvent(event)


class GraphPanel(QDialog):
    """ 全局关联有向图面板 """

    # 双击节点时发射, 主窗口据此跳到指定单词
    jump_to_word = pyqtSignal(str)

    def __init__(self, book, parent=None):
        """
        :param book: Dictionary / LearnTactics 实例
        """
        super().__init__(parent)
        self.book = book
        self.nodes = {}     # word_value -> GraphNode
        self.edges = []     # [GraphEdge]
        self._edge_map = {}  # (src,dst) -> GraphEdge, 去重用
        self._highlighted_word = None

        self.setWindowTitle('全局关联词图')
        self.resize(1000, 720)

        self._build_ui()

        # 力导向布局动画定时器(必须在 reload_graph 之前,因为后者会启动它)
        self._iter_timer = QTimer(self)
        self._iter_timer.timeout.connect(self._tick_layout)
        self._ticks_left = 0

        self.reload_graph()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        root = QVBoxLayout(self)

        # 顶部工具栏
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel('搜索:'))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText('输入单词片段, 高亮匹配节点并居中')
        self.search_edit.textChanged.connect(self._on_search)
        toolbar.addWidget(self.search_edit)

        self.only_assoc_chk = QCheckBox('仅显示有关联词')
        self.only_assoc_chk.toggled.connect(lambda _: self.reload_graph())
        toolbar.addWidget(self.only_assoc_chk)

        self.relayout_btn = QPushButton('重新布局')
        self.relayout_btn.clicked.connect(lambda: self._start_layout(220))
        toolbar.addWidget(self.relayout_btn)

        self.fit_btn = QPushButton('适配视图')
        self.fit_btn.clicked.connect(self._fit_view)
        toolbar.addWidget(self.fit_btn)

        root.addLayout(toolbar)

        # 视图
        self.view = AssociationsGraphView(self)
        self.scene = QGraphicsScene(self)
        self.view.setScene(self.scene)
        self.view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        root.addWidget(self.view, 1)

        # 底部图例
        self.legend = QLabel()
        self._build_legend()
        root.addWidget(self.legend)

    def _build_legend(self):
        parts = []
        for rank, color in RANK_COLORS.items():
            parts.append('<span style="background-color:{}; padding:0 8px; color:white; border-radius:3px;">{}</span>'.format(color.name(), rank))
        parts.append('| <b>左键</b>: 高亮邻居 &nbsp; <b>双击</b>: 跳转该词 &nbsp; <b>右键边</b>: 删除关联 &nbsp; <b>Ctrl+滚轮</b>: 缩放')
        self.legend.setTextFormat(Qt.RichText)
        self.legend.setText('&nbsp;'.join(parts))

    # ------------------------------------------------------------------ 数据
    def reload_graph(self):
        """ 依据当前 book 重建节点与边 """
        self.scene.clear()
        self.nodes.clear()
        self.edges.clear()
        self._edge_map.clear()

        only_assoc = self.only_assoc_chk.isChecked()

        # 1) 添加节点
        for wv, wobj in self.book.items():
            if only_assoc and len(wobj.associate) == 0:
                continue
            node = GraphNode(wobj, self)
            # 初始位置: 在单位圆内随机散布,避免重叠
            ang = random.uniform(0, math.tau)
            r = random.uniform(0, 180)
            node.setPos(math.cos(ang) * r, math.sin(ang) * r)
            self.scene.addItem(node)
            self.nodes[wv] = node

        # 2) 添加有向边: A -> B 当且仅当 B in A.associate
        for wv, node in self.nodes.items():
            for assoc in list(node.word_obj.associate):
                target_node = self.nodes.get(assoc)
                if target_node is None:
                    # 关联词在过滤(仅显示有关联词)下可能被隐藏, 跳过
                    continue
                key = (wv, assoc)
                if key in self._edge_map:
                    continue
                edge = GraphEdge(node, target_node, self)
                self.scene.addItem(edge)
                self.edges.append(edge)
                self._edge_map[key] = edge

        # 3) 把所有节点置顶(盖在边的上方)
        for node in self.nodes.values():
            node.setZValue(1)

        self._start_layout(220)
        self._fit_view()

    # ------------------------------------------------------------------ 力导向布局
    def _start_layout(self, ticks=200):
        self._ticks_left = ticks
        if not self._iter_timer.isActive():
            self._iter_timer.start(30)  # ~33FPS

    def _tick_layout(self):
        """ Fruchterman-Reingold 简化实现 """
        if self._ticks_left <= 0 or not self.nodes:
            self._iter_timer.stop()
            return
        self._ticks_left -= 1

        nodes_list = list(self.nodes.values())
        area = 22000.0
        k = math.sqrt(area / max(1, len(nodes_list)))
        disp = {n: QPointF(0, 0) for n in nodes_list}

        # 斥力(两两之间)
        for i, a in enumerate(nodes_list):
            for b in nodes_list[i + 1:]:
                dx = a.pos().x() - b.pos().x()
                dy = a.pos().y() - b.pos().y()
                dist = math.hypot(dx, dy) or 0.01
                # 阈值剪枝,加速收敛
                if dist > 6 * k:
                    continue
                f = (k * k) / dist
                fx = dx / dist * f
                fy = dy / dist * f
                disp[a] += QPointF(fx, fy)
                disp[b] += QPointF(-fx, -fy)

        # 引力(相邻节点)
        for e in self.edges:
            a, b = e.src, e.dst
            dx = a.pos().x() - b.pos().x()
            dy = a.pos().y() - b.pos().y()
            dist = math.hypot(dx, dy) or 0.01
            f = (dist * dist) / k
            fx = dx / dist * f
            fy = dy / dist * f
            disp[a] -= QPointF(fx, fy)
            disp[b] += QPointF(fx, fy)

        # 更新位置 + 温度冷却
        t = max(0.5, 60.0 * (self._ticks_left / 220.0))
        for n in nodes_list:
            d = disp[n]
            dlen = math.hypot(d.x(), d.y()) or 0.01
            limited = min(dlen, t)
            nx = n.pos().x() + d.x() / dlen * limited
            ny = n.pos().y() + d.y() / dlen * limited
            n.setPos(nx, ny)

        for e in self.edges:
            e.update_path()

        # 周期性更新 sceneRect
        self._update_scene_rect()

    def _update_scene_rect(self):
        if not self.nodes:
            return
        rect = QRectF()
        for n in self.nodes.values():
            rect = rect.united(n.sceneBoundingRect())
        margin = 60
        self.scene.setSceneRect(rect.adjusted(-margin, -margin, margin, margin))

    def _fit_view(self):
        if self.scene.items():
            self.view.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)

    # ------------------------------------------------------------------ 交互
    def _on_search(self, text):
        text = text.strip().lower()
        if not text:
            # 清空高亮
            for n in self.nodes.values():
                n.setOpacity(1.0)
                n.setPen(QPen(QColor('#34495e'), 1.2))
            for e in self.edges:
                e.setPen(QPen(QColor('#7f8c8d'), 1.2))
                e.setOpacity(1.0)
            return

        # 找到第一个匹配项,居中并高亮
        target = None
        for wv, n in self.nodes.items():
            if text in wv.lower():
                n.setOpacity(1.0)
                n.setPen(QPen(QColor('#c0392b'), 2.5))
                if target is None:
                    target = n
            else:
                n.setOpacity(0.25)
                n.setPen(QPen(QColor('#34495e'), 1.0))
        for e in self.edges:
            e.setOpacity(0.15)

        if target is not None:
            self.view.centerOn(target)

    def highlight_neighbors(self, word_value):
        """ 点击节点: 高亮该节点及其所有邻居和边, 其余变淡 """
        center = self.nodes.get(word_value)
        if center is None:
            return
        # 邻居集合: 关联指向的词 + 指向当前词的词
        neighbors = {word_value}
        for assoc in center.word_obj.associate:
            neighbors.add(assoc)
        for wv, n in self.nodes.items():
            if wv == word_value:
                # 反向: 谁把我加为关联词
                pass
            if word_value in n.word_obj.associate:
                neighbors.add(wv)

        for wv, n in self.nodes.items():
            if wv in neighbors:
                n.setOpacity(1.0)
                n.setPen(QPen(QColor('#c0392b'), 2.2 if wv == word_value else 1.6))
            else:
                n.setOpacity(0.25)
                n.setPen(QPen(QColor('#34495e'), 0.8))

        for e in self.edges:
            sv = e.src.word_obj.value
            dv = e.dst.word_obj.value
            if sv in neighbors and dv in neighbors:
                e.setPen(QPen(QColor('#e74c3c'), 2.0))
                e.setOpacity(1.0)
            else:
                e.setPen(QPen(QColor('#bdc3c7'), 0.8))
                e.setOpacity(0.25)

    def remove_association(self, src_word, dst_word):
        """ 右键删除关联词, 直接修改 book 中的 Vocabulary.associate """
        src_obj = self.book.get(src_word)
        if src_obj is not None:
            try:
                src_obj.associate.remove(dst_word)
            except KeyError:
                pass
        # 同步删除图中的边
        edge = self._edge_map.pop((src_word, dst_word), None)
        if edge is not None:
            self.scene.removeItem(edge)
            self.edges.remove(edge)
        QMessageBox.information(self, '已删除', '已删除关联: {} -> {}'.format(src_word, dst_word))

    # ------------------------------------------------------------------ 对外 API
    def refresh(self):
        """ 外部数据变化后刷新(主窗口保存单词后可调用) """
        for n in self.nodes.values():
            n.refresh_color()
        self.reload_graph()
