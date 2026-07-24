# -*- coding: utf-8 -*-
# @File    : Palette.py
# @Desc    : 掌握度配色表 —— 供有向图面板 / 统计报告 / 配置界面共用,
#            保证同一个 rank(掌握程度) 在各个界面里的颜色一致。
from SmartReview.Base import Vocabulary

# rank_table = ['精通','掌握','记住','清晰','模糊','混淆','忘记','顽固','待定']
# 从"已掌握"(绿) 到 "顽固/忘记"(红) 形成一条冷暖过渡的色带,越红代表越需要复习。
RANK_COLORS = {
    '精通': '#2E7D32',  # 深绿
    '掌握': '#66BB6A',  # 绿
    '记住': '#9CCC65',  # 黄绿
    '清晰': '#D4E157',  # 青柠
    '模糊': '#FFEE58',  # 黄
    '混淆': '#FFA726',  # 橙
    '忘记': '#EF5350',  # 红
    '顽固': '#B71C1C',  # 深红
    '待定': '#90A4AE',  # 灰蓝(尚无记录)
}

# 兜底颜色,遇到未知 rank 时使用
DEFAULT_COLOR = '#90A4AE'


def color_of(rank):
    """ 依据掌握程度返回十六进制颜色字符串 """
    return RANK_COLORS.get(rank, DEFAULT_COLOR)


def ordered_ranks():
    """ 返回按掌握度语义排好序的 rank 列表(与 Vocabulary.rank_table 一致) """
    return list(Vocabulary.rank_table)
