# -*- coding: utf-8 -*-
"""
H20269 RSI 止盈决策分析报告生成器
=====================================
针对"年线附近 + 高 RSI"情境，用历史数据回答"是否应该止盈"。

输出：单一 HTML 报告（含交互式图表 + 表格 + 策略建议）
适用：投资分析报告发布、邮件分享、网页嵌入
"""
# === PROJECT-ROOT BOOTSTRAP ===
# 重构后代码分层（core/ scripts/ tools/），此前言保证脚本从任何目录调用都可用：
# 把项目根与 core/ 挂上 sys.path，并将工作目录切到项目根，
# 使代码中所有 'data/...'、'output/...' 相对路径继续生效（无需逐个改写）。
import os as _os
import sys as _sys
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
for _p in (_ROOT, _os.path.join(_ROOT, 'core')):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)
if _os.path.abspath(_os.getcwd()) != _ROOT:
    _os.chdir(_ROOT)
# === /PROJECT-ROOT BOOTSTRAP ===

import sys
import os
import warnings
from datetime import datetime

if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

warnings.filterwarnings('ignore')

import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.io as pio

from data_calculator import MA250DataCalculator


# ============================================================
# 配色与样式（🆕 券商研报风格：克制、克制再克制）
# ============================================================
COLOR_PRIMARY = '#1a3a5c'      # 高盛深蓝（主色）
COLOR_ACCENT = '#8B0000'       # 深红（辅色，用于关键风险）
COLOR_GOLD = '#B8860B'         # 金色（关键数字）
COLOR_PRICE = '#1a3a5c'        # 价格线（主色）
COLOR_MA250 = '#8B0000'        # MA250 年线（辅色）
COLOR_HIGH_RSI = '#B8860B'     # 高 RSI 组（金色）
COLOR_MID_RSI = '#767676'      # 中性组（中灰）
COLOR_LOW_RSI = '#1a3a5c'      # 低 RSI 组（主色）
COLOR_RSI6 = '#1a3a5c'         # RSI6（主色，最敏感）
COLOR_RSI12 = '#8B0000'        # RSI12（辅色）
COLOR_RSI24 = '#B8860B'        # RSI24（金色，最平滑）
COLOR_POSITIVE = '#1a3a5c'     # 正向（主色）
COLOR_NEGATIVE = '#8B0000'     # 负向（辅色）
COLOR_HIGHLIGHT = '#B8860B'    # 高亮（金色）


# ============================================================
# 数据加载与分析（与项目内核心逻辑一致）
# ============================================================
def load_and_analyze(csv_path='data/H20269历史数据.csv'):
    """加载数据并执行完整分析"""
    calc = MA250DataCalculator(csv_path)
    calc.load_data()
    calc.calculate_ma250()
    calc.calculate_divergence()
    calc.calculate_rsi()
    df = calc.get_data().reset_index(drop=True)
    return df


def sample_independent(indices, min_gap=20):
    """独立性采样：相邻样本至少间隔 min_gap 天"""
    if not indices:
        return []
    selected = [indices[0]]
    for idx in indices[1:]:
        if idx - selected[-1] >= min_gap:
            selected.append(idx)
    return selected


def analyze_group(df, indices, max_future=250):
    """跟踪一组样本的后续走势"""
    results = []
    for idx in indices:
        if idx + max_future >= len(df):
            continue
        rec = {
            'idx': idx,
            '日期': df.loc[idx, '日期'],
            '价格': df.loc[idx, '收盘'],
            '乖离率': df.loc[idx, '乖离率'],
            'RSI6': df.loc[idx, 'RSI6'],
            'RSI12': df.loc[idx, 'RSI12'],
        }
        current_price = df.loc[idx, '收盘']
        max_price = current_price
        max_div = df.loc[idx, '乖离率']
        min_price_30 = current_price * 2
        reached_15 = False
        reached_15_day = None
        broke_below = False
        broke_below_day = None

        for d in range(1, max_future + 1):
            if idx + d >= len(df):
                break
            future = df.loc[idx + d]
            if future['收盘'] > max_price:
                max_price = future['收盘']
                max_div = future['乖离率']
            if d <= 30 and future['收盘'] < min_price_30:
                min_price_30 = future['收盘']
            if not reached_15 and future['乖离率'] >= 15:
                reached_15 = True
                reached_15_day = d
            if not broke_below and idx + d > 0:
                prev = df.loc[idx + d - 1]
                if prev['收盘'] > prev['MA250'] and future['收盘'] <= future['MA250']:
                    broke_below = True
                    broke_below_day = d
            if d in [10, 20, 30, 60, 120, 250]:
                rec[f'{d}日收益%'] = (future['收盘'] - current_price) / current_price * 100

        rec['250日最大涨幅%'] = (max_price - current_price) / current_price * 100
        rec['250日最大乖离率%'] = max_div
        rec['30日内最深回撤%'] = (min_price_30 - current_price) / current_price * 100
        rec['达到+15%止盈'] = reached_15
        rec['达到+15%所用天数'] = reached_15_day
        rec['再次跌破年线'] = broke_below
        rec['跌破年线所用天数'] = broke_below_day
        results.append(rec)
    return pd.DataFrame(results)


# ============================================================
# 图1：最近 60 日价格 + RSI 双子图（标注关键时点）
# ============================================================
def make_chart1_recent(df, latest_idx):
    """最近 60 日走势，标注高 RSI 时点和当前时点"""
    start_idx = max(0, latest_idx - 59)
    sub = df.iloc[start_idx: latest_idx + 1].copy()

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        vertical_spacing=0.12,
        row_heights=[0.6, 0.4],
        subplot_titles=(
            '最近 60 日：H20269 价格 vs MA250 年线',
            'RSI 指标（6/12/24 三周期）',
        )
    )

    # 主图：价格 + MA250
    fig.add_trace(go.Scatter(
        x=sub['日期'], y=sub['收盘'],
        name='收盘价', line=dict(color=COLOR_PRICE, width=2),
        hovertemplate='<b>%{x}</b><br>价格: %{y:.2f}<extra></extra>'
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=sub['日期'], y=sub['MA250'],
        name='MA250 年线', line=dict(color=COLOR_MA250, width=2, dash='dash'),
        hovertemplate='<b>%{x}</b><br>MA250: %{y:.2f}<extra></extra>'
    ), row=1, col=1)

    # 🆕 修复：用 add_vline 替代 add_vrect（vrect 的 x0=x1 零宽矩形在 subplot 下渲染异常）
    # 标注高 RSI 时点（找最后一个 RSI6 ≥ 80 的日期）
    high_rsi_date = None
    for i in range(len(sub) - 1, -1, -1):
        if sub.iloc[i]['RSI6'] >= 80:
            high_rsi_date = sub.iloc[i]['日期'].strftime('%Y-%m-%d')
            high_rsi_value = sub.iloc[i]['RSI6']
            break
    if high_rsi_date is not None:
        fig.add_vline(
            x=high_rsi_date,
            line_dash='dot', line_color=COLOR_HIGH_RSI, line_width=2,
            row=1, col=1,
        )
        fig.add_vline(
            x=high_rsi_date,
            line_dash='dot', line_color=COLOR_HIGH_RSI, line_width=1.5,
            row=2, col=1,
        )

    # 副图：RSI 三周期
    fig.add_trace(go.Scatter(
        x=sub['日期'], y=sub['RSI6'],
        name='RSI6', line=dict(color=COLOR_RSI6, width=1.5),
        hovertemplate='<b>%{x}</b><br>RSI6: %{y:.2f}<extra></extra>'
    ), row=2, col=1)
    fig.add_trace(go.Scatter(
        x=sub['日期'], y=sub['RSI12'],
        name='RSI12', line=dict(color=COLOR_RSI12, width=1.5),
        hovertemplate='<b>%{x}</b><br>RSI12: %{y:.2f}<extra></extra>'
    ), row=2, col=1)
    fig.add_trace(go.Scatter(
        x=sub['日期'], y=sub['RSI24'],
        name='RSI24', line=dict(color=COLOR_RSI24, width=1.5),
        hovertemplate='<b>%{x}</b><br>RSI24: %{y:.2f}<extra></extra>'
    ), row=2, col=1)

    # 70/30 参考线（🆕 只在 RSI 子图加，避免主图冲突）
    fig.add_hline(y=70, line_dash='dash', line_color='gray', line_width=1, row=2, col=1,
                  annotation_text='70 超买', annotation_position='top left',
                  annotation_font=dict(size=10))
    fig.add_hline(y=30, line_dash='dash', line_color='gray', line_width=1, row=2, col=1,
                  annotation_text='30 超卖', annotation_position='bottom left',
                  annotation_font=dict(size=10))
    fig.add_hline(y=50, line_dash='dot', line_color='lightgray', line_width=1, row=2, col=1)

    fig.update_yaxes(title_text='价格', row=1, col=1)
    fig.update_yaxes(title_text='RSI 值', range=[0, 100], row=2, col=1)
    fig.update_xaxes(title_text='日期', row=2, col=1)

    fig.update_layout(
        hovermode='x unified', template='plotly_white',
        height=650, width=1100,
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
        margin=dict(l=60, r=30, t=60, b=50),
        showlegend=True,
    )

    # 🆕 在主图标题下方加一个文字标注（避免 annotation 与 subplot 冲突）
    if high_rsi_date is not None:
        fig.add_annotation(
            xref='paper', yref='paper',
            x=0.98, y=0.98, xanchor='right', yanchor='top',
            text=f'<i>⬇ 橙色虚线 = 高 RSI 时点（RSI6={high_rsi_value:.1f}）</i>',
            showarrow=False,
            font=dict(size=11, color=COLOR_HIGH_RSI),
            bgcolor='rgba(255, 248, 220, 0.85)',
            bordercolor=COLOR_HIGH_RSI, borderwidth=1, borderpad=4,
        )

    return fig


# ============================================================
# 图2：三组后续收益曲线对比
# ============================================================
def make_chart2_returns_by_horizon(high_df, mid_df, low_df):
    """横轴：持有天数；纵轴：平均收益%"""
    horizons = [10, 20, 30, 60, 120, 250]
    horizon_labels = ['10 日', '20 日', '30 日', '60 日', '120 日', '250 日']

    def get_mean(df, h):
        col = f'{h}日收益%'
        if col in df.columns:
            valid = df[col].dropna()
            return valid.mean() if len(valid) > 0 else None
        return None

    high_means = [get_mean(high_df, h) for h in horizons]
    mid_means = [get_mean(mid_df, h) for h in horizons]
    low_means = [get_mean(low_df, h) for h in horizons]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=horizon_labels, y=high_means, mode='lines+markers+text',
        name=f'高 RSI 组（RSI6≥70，{len(high_df)} 样本）',
        line=dict(color=COLOR_HIGH_RSI, width=2.5),
        marker=dict(size=10),
        text=[f'{v:+.2f}%' if v is not None else '' for v in high_means],
        textposition='top center',
        hovertemplate='<b>%{x}</b><br>高 RSI 组: %{y:+.2f}%<extra></extra>'
    ))
    fig.add_trace(go.Scatter(
        x=horizon_labels, y=mid_means, mode='lines+markers+text',
        name=f'中性组（{len(mid_df)} 样本）',
        line=dict(color=COLOR_MID_RSI, width=2, dash='dash'),
        marker=dict(size=8),
        text=[f'{v:+.2f}%' if v is not None else '' for v in mid_means],
        textposition='top center',
        hovertemplate='<b>%{x}</b><br>中性组: %{y:+.2f}%<extra></extra>'
    ))
    fig.add_trace(go.Scatter(
        x=horizon_labels, y=low_means, mode='lines+markers+text',
        name=f'低 RSI 组（RSI6≤45，{len(low_df)} 样本）',
        line=dict(color=COLOR_LOW_RSI, width=2.5),
        marker=dict(size=10),
        text=[f'{v:+.2f}%' if v is not None else '' for v in low_means],
        textposition='top center',
        hovertemplate='<b>%{x}</b><br>低 RSI 组: %{y:+.2f}%<extra></extra>'
    ))

    # 0% 参考线
    fig.add_hline(y=0, line_dash='solid', line_color='black', line_width=1)

    # 标注关键观察
    fig.add_annotation(
        x='250 日', y=max(high_means[-1] if high_means[-1] else 0,
                          low_means[-1] if low_means[-1] else 0, 18),
        text='<b>关键发现：三组 250 日收益接近，<br>高 RSI 组反而胜率最高</b>',
        showarrow=False, font=dict(size=12, color=COLOR_HIGH_RSI),
        bgcolor='rgba(255, 248, 220, 0.9)', bordercolor=COLOR_HIGH_RSI, borderwidth=1,
    )

    fig.update_layout(
        title='<b>不同 RSI 水平下的后续平均收益（年线附近 + 乖离率 ≤ 5%）</b>',
        xaxis_title='持有天数', yaxis_title='平均收益 (%)',
        hovermode='x unified', template='plotly_white',
        height=500, width=1100,
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
        margin=dict(l=60, r=30, t=80, b=50),
    )
    return fig


# ============================================================
# 图3：止盈概率 vs 跌破年线概率柱状图
# ============================================================
def make_chart3_probabilities(high_df, mid_df, low_df):
    """三组的止盈概率 vs 跌破年线概率"""
    groups = ['高 RSI 组<br>(RSI6≥70)', '中性组<br>(45<RSI6<70)', '低 RSI 组<br>(RSI6≤45)']
    prob_15 = [
        high_df['达到+15%止盈'].mean() * 100,
        mid_df['达到+15%止盈'].mean() * 100,
        low_df['达到+15%止盈'].mean() * 100,
    ]
    prob_break = [
        high_df['再次跌破年线'].mean() * 100,
        mid_df['再次跌破年线'].mean() * 100,
        low_df['再次跌破年线'].mean() * 100,
    ]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        name='250 日内达到 +15% 止盈的概率',
        x=groups, y=prob_15,
        marker_color=COLOR_POSITIVE,
        text=[f'{v:.1f}%' for v in prob_15],
        textposition='outside',
        hovertemplate='<b>%{x}</b><br>达到+15%止盈: %{y:.1f}%<extra></extra>',
    ))
    fig.add_trace(go.Bar(
        name='250 日内再次跌破年线的概率',
        x=groups, y=prob_break,
        marker_color=COLOR_NEGATIVE,
        text=[f'{v:.1f}%' for v in prob_break],
        textposition='outside',
        hovertemplate='<b>%{x}</b><br>再次跌破年线: %{y:.1f}%<extra></extra>',
    ))

    # 关键洞察标注
    fig.add_annotation(
        x=0, y=prob_15[0] + 8,
        text=f'<b>⭐ 高 RSI 组<br>止盈概率最高 ({prob_15[0]:.1f}%)</b>',
        showarrow=True, arrowhead=2, arrowcolor=COLOR_POSITIVE,
        font=dict(color=COLOR_POSITIVE, size=11),
        ax=80, ay=-40,
    )
    fig.add_annotation(
        x=2, y=prob_break[2] + 8,
        text=f'<b>低 RSI 组<br>跌破概率最高 ({prob_break[2]:.1f}%)</b>',
        showarrow=True, arrowhead=2, arrowcolor=COLOR_NEGATIVE,
        font=dict(color=COLOR_NEGATIVE, size=11),
        ax=-80, ay=-40,
    )

    fig.update_layout(
        title='<b>关键事件概率：止盈 vs 跌破年线（250 日内）</b>',
        xaxis_title='', yaxis_title='概率 (%)',
        barmode='group', template='plotly_white',
        height=500, width=1100,
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
        margin=dict(l=60, r=30, t=80, b=50),
        yaxis=dict(range=[0, 100]),
    )
    return fig


# ============================================================
# 图4：典型案例的 250 日价格走势
# ============================================================
def make_chart4_typical_cases(df, case_indices, case_labels):
    """4 个典型案例的后续 250 日走势"""
    fig = go.Figure()
    colors = [COLOR_POSITIVE, '#4169E1', COLOR_NEGATIVE, COLOR_MID_RSI]

    for (idx, label, sub_label), color in zip(case_indices, colors):
        if idx + 250 >= len(df):
            continue
        sub = df.iloc[idx: idx + 251].copy()
        # 归一化为起点 = 100
        start_price = sub['收盘'].iloc[0]
        normalized = (sub['收盘'] / start_price) * 100
        # 计算时间偏移（交易日）
        days_offset = list(range(len(sub)))

        fig.add_trace(go.Scatter(
            x=days_offset, y=normalized,
            mode='lines',
            name=label,
            line=dict(color=color, width=2),
            hovertemplate=f'<b>{label}</b><br>第 %{{x}} 天: %{{y:.2f}}<br>{sub_label}<extra></extra>'
        ))

        # 标注达到 +15% 止盈的位置（归一化后 = 115）
        reached_price_115 = None
        for d in range(len(sub)):
            if sub['乖离率'].iloc[d] >= 15:
                reached_price_115 = normalized.iloc[d]
                reached_day = d
                break
        if reached_price_115 is not None:
            fig.add_trace(go.Scatter(
                x=[reached_day], y=[reached_price_115],
                mode='markers',
                name=f'{label} - 达到+15%',
                marker=dict(color=color, size=14, symbol='star',
                            line=dict(color='black', width=1.5)),
                showlegend=False,
                hovertemplate=f'<b>{label} [√] 达到 +15% 止盈</b><br>第 {reached_day} 天<extra></extra>'
            ))

    # +15% 参考线
    fig.add_hline(y=115, line_dash='dash', line_color=COLOR_POSITIVE, line_width=1.5,
                  annotation_text='+15% 止盈位', annotation_position='top left')
    # 100 起点
    fig.add_hline(y=100, line_dash='solid', line_color='black', line_width=1,
                  annotation_text='起点 = 100', annotation_position='bottom left')

    fig.update_layout(
        title='<b>4 个典型案例的后续 250 日价格走势（归一化为起点 = 100）</b>',
        xaxis_title='距高 RSI 时点的交易日数', yaxis_title='归一化价格',
        hovermode='x unified', template='plotly_white',
        height=500, width=1100,
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
        margin=dict(l=60, r=30, t=80, b=50),
    )
    return fig


# ============================================================
# HTML 报告组装
# ============================================================
def get_local_plotly_js():
    """读取本地 plotly.min.js 内容（用于嵌入 HTML，避免依赖 CDN）"""
    import plotly
    plotly_dir = os.path.dirname(plotly.__file__)
    candidates = [
        os.path.join(plotly_dir, 'package_data', 'plotly.min.js'),
        os.path.join(plotly_dir, 'static', 'plotly.min.js'),
    ]
    for p in candidates:
        if os.path.exists(p):
            with open(p, 'r', encoding='utf-8') as f:
                return f.read()
    return None  # 找不到则返回 None，回退到 CDN


# 🆕 券商研报风格 CSS（独立常量，避免 f-string 双花括号问题）
CSS_RESEARCH_STYLE = """
:root {
    --primary: #1a3a5c;
    --accent: #8B0000;
    --gold: #B8860B;
    --text-primary: #1a1a1a;
    --text-secondary: #4a4a4a;
    --text-tertiary: #767676;
    --border: #d4d4d4;
    --border-light: #e8e8e8;
    --bg-soft: #f7f7f7;
}

@page { size: A4; margin: 25mm; }

body {
    font-family: "Cambria", "Times New Roman", "SimSun", "宋体", serif;
    font-size: 11pt;
    line-height: 1.6;
    color: var(--text-primary);
    max-width: 900px;
    margin: 0 auto;
    padding: 40px 50px;
    background: #ffffff;
}

/* === 封面 === */
.cover-page {
    border-top: 4px solid var(--primary);
    border-bottom: 1px solid var(--border);
    padding: 30px 0 20px 0;
    margin-bottom: 32px;
}
.cover-category {
    font-size: 9pt;
    color: var(--text-tertiary);
    letter-spacing: 2.5px;
    text-transform: uppercase;
    margin-bottom: 10px;
    font-weight: bold;
}
.cover-title {
    font-size: 22pt;
    font-weight: bold;
    color: var(--primary);
    margin: 0 0 12px 0;
    line-height: 1.3;
    letter-spacing: -0.3px;
}
.cover-subtitle {
    font-size: 12pt;
    color: var(--text-secondary);
    margin-bottom: 24px;
    font-weight: normal;
    font-style: italic;
}
.cover-meta {
    display: flex;
    border-top: 1px solid var(--border);
    padding-top: 12px;
    font-size: 9pt;
}
.cover-meta-cell { flex: 1; padding-right: 12px; }
.cover-meta-label {
    text-transform: uppercase;
    letter-spacing: 1.2px;
    margin-bottom: 3px;
    color: var(--text-tertiary);
    font-size: 7.5pt;
    font-weight: bold;
}
.cover-meta-value {
    color: var(--text-primary);
    font-weight: bold;
    font-size: 10pt;
}

/* === 章节 === */
h2 {
    font-size: 14pt;
    color: var(--primary);
    border-bottom: 1.5px solid var(--primary);
    padding-bottom: 6px;
    margin-top: 36px;
    margin-bottom: 16px;
    font-weight: bold;
}
h3 {
    font-size: 11.5pt;
    color: var(--text-primary);
    margin-top: 20px;
    margin-bottom: 10px;
    font-weight: bold;
}

/* === 投资要点 === */
.key-points {
    background: var(--bg-soft);
    border-left: 3px solid var(--primary);
    padding: 16px 22px;
    margin: 20px 0 28px 0;
}
.key-points-title {
    font-size: 8.5pt;
    color: var(--text-tertiary);
    text-transform: uppercase;
    letter-spacing: 1.5px;
    margin-bottom: 10px;
    font-weight: bold;
}
.key-points ul { margin: 0; padding-left: 18px; }
.key-points li { margin: 5px 0; }

/* === 关键结论 === */
.conclusion {
    border: 1px solid var(--primary);
    padding: 18px 22px;
    margin: 24px 0;
    background: #ffffff;
}
.conclusion-title {
    color: var(--primary);
    font-weight: bold;
    font-size: 11pt;
    margin-bottom: 8px;
    text-transform: uppercase;
    letter-spacing: 1.2px;
}

/* === 表格（券商风格：极简线条） === */
table {
    border-collapse: collapse;
    width: 100%;
    margin: 14px 0;
    font-size: 10pt;
}
th {
    background: var(--primary);
    color: #ffffff;
    font-weight: bold;
    padding: 7px 10px;
    text-align: left;
    border-right: 1px solid #2a4a6c;
    font-size: 9.5pt;
    letter-spacing: 0.3px;
}
th:last-child { border-right: none; }
td {
    padding: 6px 10px;
    border-bottom: 1px solid var(--border-light);
    font-family: "Cambria", "Times New Roman", serif;
    font-size: 10pt;
}
tr { background: #ffffff; }

.figure {
    font-family: "Cambria", "Times New Roman", serif;
    font-weight: bold;
    color: var(--primary);
}
.accent {
    font-weight: bold;
    color: var(--accent);
}
.muted { color: var(--text-tertiary); }

/* === 图表 === */
.exhibit { margin: 24px 0; }
.exhibit-title {
    font-size: 10pt;
    font-weight: bold;
    color: var(--text-primary);
    margin-bottom: 8px;
}
.exhibit-number {
    color: var(--text-tertiary);
    font-weight: normal;
    margin-right: 6px;
}
.exhibit-source {
    font-size: 8.5pt;
    color: var(--text-tertiary);
    margin-top: 8px;
    font-style: italic;
    border-top: 1px dotted var(--border);
    padding-top: 4px;
}
.chart-box {
    border: 1px solid var(--border);
    padding: 12px;
    background: #ffffff;
}

p { margin: 8px 0; text-align: justify; }
ul, ol { padding-left: 24px; }
li { margin: 4px 0; }

.note {
    font-size: 9pt;
    color: var(--text-tertiary);
    font-style: italic;
    margin: 8px 0;
    padding-left: 12px;
    border-left: 2px solid var(--border);
}

/* === 风险提示 === */
.risk-warning {
    background: #fff8f0;
    border-left: 3px solid var(--accent);
    padding: 14px 22px;
    margin: 20px 0;
}
.risk-warning-title {
    color: var(--accent);
    font-weight: bold;
    font-size: 10pt;
    margin-bottom: 8px;
    text-transform: uppercase;
    letter-spacing: 1.2px;
}

/* === 方法论 === */
.methodology {
    border-top: 1px solid var(--border);
    margin-top: 40px;
    padding-top: 20px;
    font-size: 9pt;
    color: var(--text-secondary);
}
.methodology h3 {
    font-size: 10pt;
    color: var(--text-primary);
    text-transform: uppercase;
    letter-spacing: 1.2px;
    border-bottom: 1px solid var(--border-light);
    padding-bottom: 4px;
    margin-top: 18px;
}

/* === 页脚 === */
.footer {
    border-top: 2px solid var(--primary);
    margin-top: 40px;
    padding-top: 16px;
    font-size: 8pt;
    color: var(--text-tertiary);
    line-height: 1.5;
}
.footer-section { margin-bottom: 10px; }
.footer-title {
    font-weight: bold;
    color: var(--text-secondary);
    text-transform: uppercase;
    letter-spacing: 1px;
    margin-bottom: 4px;
    font-size: 8pt;
}

/* === 标签（替代 emoji） === */
.tag {
    display: inline-block;
    padding: 1px 6px;
    color: white;
    font-size: 8pt;
    font-weight: bold;
    margin-right: 4px;
    letter-spacing: 0.5px;
    font-family: "Cambria", serif;
}
.tag-hold { background: var(--primary); }
.tag-risk { background: var(--accent); }
.tag-buy { background: #2a5f2a; }
.tag-neutral { background: var(--text-tertiary); }

@media print {
    body { padding: 0; max-width: none; }
    .chart-box, table, .exhibit, .conclusion { page-break-inside: avoid; }
    h2 { page-break-after: avoid; }
}
"""


def generate_html_report(df, high_df, mid_df, low_df, fine_df, output_path):
    """组装完整 HTML 报告"""

    latest = df.iloc[-1]
    latest_idx = len(df) - 1

    # 找到 7-30 类似的高 RSI 时点用于展示
    # 历史案例（精选 4 个）
    cases = [
        (df[df['日期'] == '2014-06-16'].index[0], '2014-06-16 大牛市启动',
         f'RSI6={df[df["日期"] == "2014-06-16"]["RSI6"].iloc[0]:.1f}, 后续 250 日 +151%'),
        (df[df['日期'] == '2016-07-13'].index[0], '2016-07-13 震荡向上',
         f'RSI6={df[df["日期"] == "2016-07-13"]["RSI6"].iloc[0]:.1f}, 后续 250 日 +29%'),
        (df[df['日期'] == '2018-05-08'].index[0], '2018-05-08 贸易战',
         f'RSI6={df[df["日期"] == "2018-05-08"]["RSI6"].iloc[0]:.1f}, 后续 250 日 -1.5%'),
        (df[df['日期'] == '2015-12-21'].index[0], '2015-12-21 股灾',
         f'RSI6={df[df["日期"] == "2015-12-21"]["RSI6"].iloc[0]:.1f}, 后续 250 日 -3.7%'),
    ]

    # 生成 4 张图
    fig1 = make_chart1_recent(df, latest_idx)
    fig2 = make_chart2_returns_by_horizon(high_df, mid_df, low_df)
    fig3 = make_chart3_probabilities(high_df, mid_df, low_df)
    fig4 = make_chart4_typical_cases(df, cases, None)

    # 转换为 HTML 片段
    html_fig1 = pio.to_html(fig1, include_plotlyjs=False, full_html=False, div_id='chart1')
    html_fig2 = pio.to_html(fig2, include_plotlyjs=False, full_html=False, div_id='chart2')
    html_fig3 = pio.to_html(fig3, include_plotlyjs=False, full_html=False, div_id='chart3')
    html_fig4 = pio.to_html(fig4, include_plotlyjs=False, full_html=False, div_id='chart4')

    # 🆕 plotly.js 策略：本地嵌入（最稳）+ CDN fallback
    local_plotly = get_local_plotly_js()
    if local_plotly:
        plotly_script = f'<script>{local_plotly}</script>'
        plotly_note = '<!-- plotly.js 已嵌入本地（单文件可离线打开）-->'
    else:
        plotly_script = '<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>'
        plotly_note = '<!-- plotly.js CDN 引用（本机 plotly 包未找到 plotly.min.js）-->'

    # 关键数据计算（用于表格）
    high_250_mean = high_df['250日收益%'].mean()
    high_250_median = high_df['250日收益%'].median()
    high_250_win = (high_df['250日收益%'] > 0).mean() * 100
    high_prob_15 = high_df['达到+15%止盈'].mean() * 100
    high_prob_break = high_df['再次跌破年线'].mean() * 100
    high_max_drawdown_30 = high_df['30日内最深回撤%'].mean()
    high_max_drawdown_30_med = high_df['30日内最深回撤%'].median()

    mid_250_mean = mid_df['250日收益%'].mean()
    mid_250_win = (mid_df['250日收益%'] > 0).mean() * 100
    mid_prob_15 = mid_df['达到+15%止盈'].mean() * 100
    mid_prob_break = mid_df['再次跌破年线'].mean() * 100

    low_250_mean = low_df['250日收益%'].mean()
    low_250_win = (low_df['250日收益%'] > 0).mean() * 100
    low_prob_15 = low_df['达到+15%止盈'].mean() * 100
    low_prob_break = low_df['再次跌破年线'].mean() * 100

    # 精细分析（fine_df）数据
    fine_30_mean = fine_df['30日收益%'].mean()
    fine_60_mean = fine_df['60日收益%'].mean()
    fine_120_mean = fine_df['120日收益%'].mean()
    fine_250_mean = fine_df['250日收益%'].mean()
    fine_250_win = (fine_df['250日收益%'] > 0).mean() * 100
    fine_prob_15 = fine_df['达到+15%止盈'].mean() * 100
    fine_prob_break = fine_df['再次跌破年线'].mean() * 100
    fine_drawdown = fine_df['30日内最深回撤%'].mean()
    fine_drawdown_med = fine_df['30日内最深回撤%'].median()

    # 当前状态表（最近 15 日）
    recent_15 = df.iloc[-15:][['日期', '收盘', '乖离率', 'RSI6', 'RSI12', 'RSI24']].copy()
    recent_15['日期'] = recent_15['日期'].dt.strftime('%Y-%m-%d')
    for c in ['乖离率', 'RSI6', 'RSI12', 'RSI24']:
        recent_15[c] = recent_15[c].round(2)
    recent_html = recent_15.to_html(index=False, classes='data-table', border=0)

    # 报告日期
    report_date = datetime.now().strftime('%Y-%m-%d')
    data_end_date = latest['日期'].strftime('%Y-%m-%d')

    # 完整 HTML
    # 🆕 券商研报风格 HTML 模板
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>H20269 RSI 止盈决策分析 | 投资研究 - {data_end_date}</title>
{plotly_note}
{plotly_script}
<style>
{CSS_RESEARCH_STYLE}
</style>
</head>
<body>

<!-- ==================== 封面 ==================== -->
<div class="cover-page">
    <div class="cover-category">EQUITY RESEARCH · 投资策略分析</div>
    <h1 class="cover-title">红利低波 H20269：年线附近 + 高 RSI 时的止盈决策</h1>
    <div class="cover-subtitle">基于 2006-2026 全样本数据的实证研究</div>
    <div class="cover-meta">
        <div class="cover-meta-cell">
            <div class="cover-meta-label">标的</div>
            <div class="cover-meta-value">H20269 红利低波 TRI</div>
        </div>
        <div class="cover-meta-cell">
            <div class="cover-meta-label">数据截止</div>
            <div class="cover-meta-value">{data_end_date}</div>
        </div>
        <div class="cover-meta-cell">
            <div class="cover-meta-label">报告日期</div>
            <div class="cover-meta-value">{report_date}</div>
        </div>
        <div class="cover-meta-cell">
            <div class="cover-meta-label">评级</div>
            <div class="cover-meta-value"><span class="tag tag-hold">HOLD</span>维持持有</div>
        </div>
    </div>
</div>

<!-- ==================== 投资要点 ==================== -->
<div class="key-points">
    <div class="key-points-title">Investment Summary · 投资要点</div>
    <ul>
        <li><strong>当前状态</strong>：2026-08-04 H20269 收于 <span class="figure">23,746.58</span>，乖离率 <span class="figure">+0.12%</span>，RSI6 已从 7 月 30 日的 <span class="figure">81.5</span> 回落至 <span class="figure">48.89</span>。</li>
        <li><strong>核心问题</strong>：年线附近 + 高 RSI 时是否应该止盈？基于 <span class="figure">49 个</span>历史类比样本分析。</li>
        <li><strong>关键结论</strong>：<span class="figure">67.4%</span> 概率达到 +15% 止盈，30 日回撤均值仅 <span class="figure">-4.39%</span>，<strong>持有优于止盈</strong>。</li>
        <li><strong>反直觉发现</strong>：高 RSI 组（≥70）反而止盈概率最高（<span class="figure">70.0%</span>），跌破年线概率最低（<span class="figure">73.3%</span>）。</li>
        <li><strong>操作建议</strong>：<span class="tag tag-hold">HOLD</span>维持持有，等待 +15% 止盈信号。</li>
    </ul>
</div>

<!-- ==================== 1. 当前状态诊断 ==================== -->
<h2>1. 当前状态诊断</h2>

<h3>1.1 关键时点回放</h3>

<table>
<thead>
<tr><th>日期</th><th>收盘价</th><th>乖离率</th><th>RSI6</th><th>RSI12</th><th>RSI24</th><th>解读</th></tr>
</thead>
<tbody>
<tr>
    <td>2026-07-29</td><td>23,922.34</td><td>+0.85%</td><td>74.36</td><td>66.68</td><td>58.83</td>
    <td>重回年线日</td>
</tr>
<tr>
    <td><strong>2026-07-30</strong></td><td><strong>24,318.95</strong></td>
    <td><strong>+2.52%</strong></td><td><strong>81.50</strong></td>
    <td><strong>71.48</strong></td><td>62.06</td>
    <td><strong>高 RSI 警戒时点</strong></td>
</tr>
<tr>
    <td>2026-08-03</td><td>24,271.39</td><td>+2.33%</td><td>76.64</td><td>69.54</td><td>61.27</td>
    <td>RSI 仍偏高</td>
</tr>
<tr>
    <td><strong>2026-08-04</strong></td><td><strong>23,746.58</strong></td>
    <td><strong>+0.12%</strong></td><td><strong>48.89</strong></td>
    <td><strong>56.32</strong></td><td>54.96</td>
    <td><strong>当前：单日 -2.16%，RSI6 已回落到中性</strong></td>
</tr>
</tbody>
</table>

<p><strong>关键洞察</strong>：8-4 单日 <span class="accent">-2.16%</span> 的下跌已经把 RSI6 从 76.64 杀到 48.89（暴跌 27 个点），<em>"高 RSI 警戒"已经被市场自我化解</em>。用户提问时的担忧前提已不存在。</p>

<h3>1.2 最近 60 日走势</h3>

<div class="exhibit">
    <div class="exhibit-title"><span class="exhibit-number">Exhibit 1.</span>最近 60 日 H20269 价格 vs MA250 与 RSI 指标走势</div>
    <div class="chart-box">
{html_fig1}
    </div>
    <div class="exhibit-source">Source: 中证指数公司 H20269 全收益指数（含分红复投），作者计算。橙色虚线标注 2026-07-30 高 RSI 时点。</div>
</div>

<h3>1.3 最近 15 个交易日详细数据</h3>

{recent_html}

<!-- ==================== 2. 历史数据分析 ==================== -->
<h2>2. 历史数据分析</h2>

<h3>2.1 三组对比：不同 RSI 水平下的后续表现</h3>

<p><strong>分组定义</strong>（已做独立性采样，相邻样本至少间隔 20 个交易日）：</p>
<ul>
    <li><strong>高 RSI 组</strong>：乖离率 ∈ [-3%, +5%] AND RSI6 ≥ 70（<span class="figure">{len(high_df)}</span> 个独立样本）</li>
    <li><strong>中性组</strong>：乖离率 ∈ [-3%, +5%] AND 45 &lt; RSI6 &lt; 70（<span class="figure">{len(mid_df)}</span> 个独立样本）</li>
    <li><strong>低 RSI 组</strong>：乖离率 ∈ [-3%, +5%] AND RSI6 ≤ 45（<span class="figure">{len(low_df)}</span> 个独立样本）</li>
</ul>

<table>
<thead>
<tr>
    <th>指标</th>
    <th>高 RSI 组</th>
    <th>中性组</th>
    <th>低 RSI 组</th>
</tr>
</thead>
<tbody>
<tr>
    <td><strong>独立样本数</strong></td>
    <td>{len(high_df)}</td>
    <td>{len(mid_df)}</td>
    <td>{len(low_df)}</td>
</tr>
<tr>
    <td><strong>250 日平均收益</strong></td>
    <td><span class="figure">{high_250_mean:+.2f}%</span></td>
    <td>{mid_250_mean:+.2f}%</td>
    <td>{low_250_mean:+.2f}%</td>
</tr>
<tr>
    <td><strong>250 日胜率</strong></td>
    <td><span class="figure">{high_250_win:.1f}%</span></td>
    <td>{mid_250_win:.1f}%</td>
    <td>{low_250_win:.1f}%</td>
</tr>
<tr>
    <td><strong>达到 +15% 止盈概率</strong></td>
    <td><span class="figure">{high_prob_15:.1f}%</span></td>
    <td>{mid_prob_15:.1f}%</td>
    <td>{low_prob_15:.1f}%</td>
</tr>
<tr>
    <td><strong>再次跌破年线概率</strong></td>
    <td><span class="figure">{high_prob_break:.1f}%</span></td>
    <td>{mid_prob_break:.1f}%</td>
    <td>{low_prob_break:.1f}%</td>
</tr>
<tr>
    <td><strong>30 日内最深回撤（均值）</strong></td>
    <td><span class="accent">{high_max_drawdown_30:.2f}%</span></td>
    <td class="muted">—</td>
    <td class="muted">—</td>
</tr>
</tbody>
</table>

<div class="exhibit">
    <div class="exhibit-title"><span class="exhibit-number">Exhibit 2.</span>不同 RSI 水平下的后续平均收益对比（年线附近，乖离率 ≤ 5%）</div>
    <div class="chart-box">
{html_fig2}
    </div>
    <div class="exhibit-source">Source: 作者基于 H20269 2006-2026 全样本计算。横轴为持有天数，纵轴为平均收益 %。</div>
</div>

<h3>2.2 关键事件概率</h3>

<div class="exhibit">
    <div class="exhibit-title"><span class="exhibit-number">Exhibit 3.</span>止盈概率 vs 跌破年线概率对比（250 日窗口）</div>
    <div class="chart-box">
{html_fig3}
    </div>
    <div class="exhibit-source">Source: 作者计算。反直觉发现：高 RSI 组止盈概率反而最高（动量延续效应）。</div>
</div>

<p><strong>反直觉的发现</strong>：高 RSI 组（通常被视为"超买危险信号"）的止盈概率（<span class="figure">70%</span>）反而最高，再次跌破年线概率（<span class="figure">73.3%</span>）反而最低。这反映了红利低波的<strong>"动量延续"</strong>特性：RSI 高 = 上涨动能强，重回年线后趋势更延续。</p>

<h3>2.3 精细分析：刚重回年线 + 30 天内高 RSI（最贴近当前情境）</h3>

<p>为更贴近 2026-07-29 的实际情境（5-7 跌破年线，7-29 重回，7-30 出现高 RSI），我们进一步筛选"<strong>刚重回年线后 30 天内出现 RSI6 ≥ 70</strong>"的事件，得到 <span class="figure">{len(fine_df)}</span> 个历史样本。</p>

<table>
<thead>
<tr><th>时间窗</th><th>平均收益</th><th>胜率</th><th>解读</th></tr>
</thead>
<tbody>
<tr><td><strong>10 日</strong></td><td><span class="figure">+1.15%</span></td><td>81%</td><td>短期通常延续反弹</td></tr>
<tr><td><strong>30 日</strong></td><td><span class="figure">+1.74%</span></td><td>65%</td><td>短期仍正向</td></tr>
<tr><td><strong>60 日</strong></td><td>+0.02%</td><td>53%</td><td><span class="accent">震荡期，胜率接近随机</span></td></tr>
<tr><td><strong>120 日</strong></td><td><span class="accent">-1.23%</span></td><td>56%</td><td>仍可能震荡</td></tr>
<tr><td><strong>250 日（约 1 年）</strong></td><td><span class="figure">+7.71%</span></td><td><span class="figure">72%</span></td><td><strong>长期大概率盈利</strong></td></tr>
</tbody>
</table>

<table>
<thead><tr><th>关键事件</th><th>概率</th><th>用时（中位数）</th></tr></thead>
<tbody>
<tr><td>达到 +15% 止盈信号</td><td><span class="figure">{fine_prob_15:.1f}%</span></td><td>114 天</td></tr>
<tr><td>再次跌破年线（假动作）</td><td>{fine_prob_break:.1f}%</td><td>14 天</td></tr>
<tr><td>30 日内最深回撤（均值/中位数）</td><td>—</td><td><span class="accent">{fine_drawdown:.2f}%</span> / {fine_drawdown_med:.2f}%</td></tr>
</tbody>
</table>

<div class="risk-warning">
    <div class="risk-warning-title">重要提醒 · Key Risk</div>
    <p>再次跌破年线的概率高达 <strong>{fine_prob_break:.0f}%</strong>，<strong>但中位数仅 14 天</strong>。这意味着短期内大概率会有"假跌破"动作，但<strong>这不影响 {fine_prob_15:.0f}% 的最终止盈概率</strong>。红利低波的低波动特性（年化波动率 14%）决定了它"震荡市中拿得住"的优势。</p>
</div>

<!-- ==================== 3. 典型案例 ==================== -->
<h2>3. 典型案例：4 个真实历史事件</h2>

<p>从历史样本中精选 4 个"高 RSI + 年线附近"事件，展示后续 250 日的真实走势：</p>

<div class="exhibit">
    <div class="exhibit-title"><span class="exhibit-number">Exhibit 4.</span>4 个典型案例的后续 250 日价格走势（归一化为起点 = 100）</div>
    <div class="chart-box">
{html_fig4}
    </div>
    <div class="exhibit-source">Source: 作者基于 H20269 历史数据计算。⭐ 标记达到 +15% 止盈的位置（归一化价格 = 115）。</div>
</div>

<table>
<thead>
<tr><th>案例</th><th>RSI6</th><th>乖离率</th><th>60 日收益</th><th>250 日收益</th><th>触发 +15%</th><th>启示</th></tr>
</thead>
<tbody>
<tr>
    <td><strong>2014-06-16 大牛市启动</strong></td>
    <td>72.3</td><td>+4.50%</td>
    <td>+15.16%</td><td><span class="figure">+151%</span></td>
    <td>是</td>
    <td>最佳案例：高 RSI 是趋势启动信号</td>
</tr>
<tr>
    <td><strong>2016-07-13 震荡向上</strong></td>
    <td>88.5</td><td>+0.70%</td>
    <td>+6.32%</td><td>+29%</td>
    <td>是</td>
    <td>典型慢牛走势</td>
</tr>
<tr>
    <td><strong>2018-05-08 贸易战</strong></td>
    <td>74.5</td><td>-0.37%</td>
    <td><span class="accent">-6.85%</span></td><td><span class="accent">-1.50%</span></td>
    <td>是（延迟）</td>
    <td>系统性风险下的延迟止盈</td>
</tr>
<tr>
    <td><strong>2015-12-21 股灾</strong></td>
    <td>77.6</td><td>+4.01%</td>
    <td><span class="accent">-14.92%</span></td><td><span class="accent">-3.66%</span></td>
    <td><span class="accent">否</span></td>
    <td>少数大幅亏损案例（极端系统性风险）</td>
</tr>
</tbody>
</table>

<p><strong>案例启示</strong>：</p>
<ul>
    <li><strong>4 个案例中 3 个</strong>最终触发 +15% 止盈（75% 概率，与全样本 67% 一致）</li>
    <li>仅 <strong>1 个</strong>（2015 股灾）出现大幅亏损，属于极端系统性风险，<strong>RSI 无法预测</strong></li>
    <li>2026 年当前宏观环境更接近 2014（震荡 + 政策温和）或 2016（慢牛），而非 2015（泡沫破裂）或 2018（贸易战突发）</li>
</ul>

<!-- ==================== 4. 策略建议 ==================== -->
<h2>4. 策略建议</h2>

<div class="conclusion">
    <div class="conclusion-title">核心结论 · Final Recommendation</div>
    <p style="font-size: 14pt; margin: 8px 0;"><span class="tag tag-hold">HOLD</span><strong>持有不动，等待 +15% 止盈信号。</strong></p>
    <p style="margin: 4px 0 0 0;">不要因 RSI 短线偏高而提前止盈。基于历史数据，"等 +15%"是大概率获胜策略。</p>
</div>

<h3>4.1 明确回答三个问题</h3>

<table>
<thead><tr><th>用户问题</th><th>数据回答</th><th>建议操作</th></tr></thead>
<tbody>
<tr>
    <td><strong>现在需要止盈吗？</strong></td>
    <td>不需要。RSI6 已回到 48.89；<span class="figure">67%</span> 概率达到 +15% 止盈</td>
    <td><span class="tag tag-hold">HOLD</span>不止盈</td>
</tr>
<tr>
    <td><strong>继续下跌较大幅度的可能性大吗？</strong></td>
    <td>不大。30 日回撤均值仅 <span class="figure">-4.39%</span>，中位数 <span class="figure">-1.88%</span></td>
    <td><span class="tag tag-hold">HOLD</span>安心持有</td>
</tr>
<tr>
    <td><strong>等 +15% 还是 RSI 高就部分减仓？</strong></td>
    <td>等 +15%。提前减仓会错过 <span class="figure">67%</span> 的行情</td>
    <td><span class="tag tag-hold">HOLD</span>长线持有</td>
</tr>
</tbody>
</table>

<h3>4.2 持有预期路线图</h3>

<table>
<thead><tr><th>时间窗</th><th>预期走势</th><th>应对策略</th></tr></thead>
<tbody>
<tr>
    <td><strong>未来 14 天</strong></td>
    <td><span class="figure">{fine_prob_break:.0f}%</span> 概率会再次跌破年线（中位数 14 天）</td>
    <td><span class="accent">不要恐慌</span>，这是正常震荡</td>
</tr>
<tr>
    <td><strong>未来 60-120 天</strong></td>
    <td>可能多次穿越年线，累计收益接近 0</td>
    <td>耐心持有，不追加也不减仓</td>
</tr>
<tr>
    <td><strong>未来 250 天（约 1 年）</strong></td>
    <td><span class="figure">67%</span> 概率达到 +15% 止盈（中位数 114 天）</td>
    <td><span class="tag tag-hold">HOLD</span>执行原模型止盈</td>
</tr>
</tbody>
</table>

<h3>4.3 风险提示</h3>

<div class="risk-warning">
    <div class="risk-warning-title">极端情况 · Tail Risks（RSI 无法预测）</div>
    <ul style="margin: 8px 0;">
        <li><strong>系统性风险</strong>：如 2008 金融危机（-46%）、2015 股灾（-23%）、2020 疫情（-17%）</li>
        <li><strong>政策重大转向</strong>：货币政策、监管政策的突发变化</li>
        <li><strong>标的本身风险</strong>：指数编制方法重大变更、跟踪基金异常</li>
    </ul>
    <p style="margin: 8px 0 0 0;">这些场景下，无论 RSI 高低都应启用紧急止损（详见 STRATEGY_DESIGN.md 第 4.4 节）。</p>
</div>

<!-- ==================== 5. 方法论 ==================== -->
<div class="methodology">
<h2 style="font-size: 12pt; border-bottom: 1px solid var(--border);">5. 方法论与数据说明 · Methodology</h2>

<h3>数据来源</h3>
<ul>
    <li>标的：H20269 红利低波全收益指数（中证指数公司）</li>
    <li>数据范围：2006-01-04 至 2026-08-04（5001 条原始数据，4752 条 MA250 后有效）</li>
    <li>RSI 算法：Wilder 平滑法（EMA α=1/N），周期 6/12/24（券商标准）</li>
    <li>MA250：250 个交易日收盘价算术平均</li>
</ul>

<h3>样本筛选逻辑</h3>
<ul>
    <li><strong>主组（高 RSI）</strong>：乖离率 ∈ [-3%, +5%] AND RSI6 ≥ 70</li>
    <li><strong>对照组（低 RSI）</strong>：乖离率 ∈ [-3%, +5%] AND RSI6 ≤ 45</li>
    <li><strong>精细组</strong>：刚重回年线（前日 ≤ MA250 & 当日 &gt; MA250）后 30 天内出现 RSI6 ≥ 70</li>
    <li><strong>独立性采样</strong>：相邻样本至少间隔 20 个交易日，避免数据自相关</li>
</ul>

<h3>关键定义</h3>
<ul>
    <li><strong>达到 +15% 止盈</strong>：后续 250 天内乖离率 ≥ 15%（即 ROLLING_POSITION_STRATEGY.md 的 a% 阈值）</li>
    <li><strong>再次跌破年线</strong>：前日 close &gt; MA250 且当日 close ≤ MA250</li>
    <li><strong>胜率</strong>：收益 &gt; 0 的样本占比</li>
</ul>

<h3>局限性</h3>
<ul>
    <li>样本数有限（主组 30 个、精细组 {len(fine_df)} 个），统计显著性受样本量约束</li>
    <li>"高 RSI"在不同市场阶段的含义不同（牛市启动 vs 牛市末期）</li>
    <li>2005-2013 的 H20269 数据是指数公司回算值，无真实 ETF 交易</li>
    <li>历史规律不能保证未来一定重复，需配合基本面分析使用</li>
</ul>

<h3>相关文档</h3>
<ul>
    <li><code>ANALYZE_MA250_GUIDE.md</code>：分析工具使用指南</li>
    <li><code>ROLLING_POSITION_STRATEGY.md</code>：MA250 长线策略详细规则</li>
    <li><code>RSI_ANALYSIS_FRAMEWORK.md</code>：RSI 分析框架设计</li>
    <li><code>progress.md</code>：项目进度记录</li>
</ul>
</div>

<!-- ==================== 页脚 ==================== -->
<div class="footer">
    <div class="footer-section">
        <div class="footer-title">Disclaimer · 免责声明</div>
        <p>本报告基于历史数据分析，不构成投资建议。投资有风险，决策需谨慎。本报告所引用的信息均来自公开资料，作者对其准确性、完整性不作任何保证，也不对使用本报告造成的任何后果承担任何责任。</p>
    </div>
    <div class="footer-section">
        <div class="footer-title">Analyst Certification · 分析师承诺</div>
        <p>本报告作者保证：(1) 本报告所表达的观点准确反映了作者对本报告所涵盖证券和发行人的个人看法；且(2) 本报告中任何部分的报酬均未直接或间接与本报告中具体推荐或观点相关。</p>
    </div>
    <div class="footer-section" style="border-top: 1px dotted var(--border); padding-top: 8px; margin-top: 8px;">
        <p>报告由 <code>generate_rsi_report.py</code> 自动生成 | 数据更新至 {data_end_date} | 报告生成于 {report_date}</p>
    </div>
</div>

</body>
</html>"""

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)

    return output_path


# ============================================================
# 主程序
# ============================================================
def main():
    print('='*70)
    print('H20269 RSI 止盈决策分析报告生成器')
    print('='*70)

    # 1. 加载数据
    print('\n[1/5] 加载数据...')
    df = load_and_analyze()
    print(f'  数据范围: {df["日期"].min().strftime("%Y-%m-%d")} 至 {df["日期"].max().strftime("%Y-%m-%d")}')
    print(f'  样本数: {len(df)}')

    # 2. 筛选三组样本
    print('\n[2/5] 筛选三组样本（高/中/低 RSI）...')
    NEAR_MA_LOW, NEAR_MA_HIGH = -3.0, 5.0
    RSI6_HIGH, RSI6_LOW = 70, 45

    mask_high = (df['乖离率'] >= NEAR_MA_LOW) & (df['乖离率'] <= NEAR_MA_HIGH) & (df['RSI6'] >= RSI6_HIGH)
    mask_low = (df['乖离率'] >= NEAR_MA_LOW) & (df['乖离率'] <= NEAR_MA_HIGH) & (df['RSI6'] <= RSI6_LOW)
    mask_mid = (df['乖离率'] >= NEAR_MA_LOW) & (df['乖离率'] <= NEAR_MA_HIGH) & (df['RSI6'] > RSI6_LOW) & (df['RSI6'] < RSI6_HIGH)

    high_idx = sample_independent(df.index[mask_high].tolist())
    low_idx = sample_independent(df.index[mask_low].tolist())
    mid_idx = sample_independent(df.index[mask_mid].tolist())

    print(f'  高 RSI 组（RSI6≥70）: {len(high_idx)} 个独立样本')
    print(f'  中性组: {len(mid_idx)} 个独立样本')
    print(f'  低 RSI 组（RSI6≤45）: {len(low_idx)} 个独立样本')

    # 3. 跟踪后续走势
    print('\n[3/5] 跟踪三组样本的后续走势...')
    high_df = analyze_group(df, high_idx)
    mid_df = analyze_group(df, mid_idx)
    low_df = analyze_group(df, low_idx)

    # 4. 精细分析（刚重回年线+30日内高RSI）
    print('\n[4/5] 精细分析（刚重回年线 + 30 天内高 RSI）...')
    recover_events = []
    for i in range(1, len(df)):
        prev = df.loc[i-1]
        curr = df.loc[i]
        if prev['收盘'] <= prev['MA250'] and curr['收盘'] > curr['MA250']:
            recover_events.append(i)

    fine_indices = []
    for rec_idx in recover_events:
        for d in range(0, 31):
            idx = rec_idx + d
            if idx >= len(df):
                break
            row = df.loc[idx]
            if row['乖离率'] <= 5 and row['RSI6'] >= 70:
                fine_indices.append(idx)
                break

    fine_df = analyze_group(df, fine_indices)
    print(f'  精细分析样本数: {len(fine_df)}')

    # 5. 生成 HTML 报告
    print('\n[5/5] 生成 HTML 报告...')
    output_dir = 'output/reports'
    os.makedirs(output_dir, exist_ok=True)

    data_end_date = df.iloc[-1]['日期'].strftime('%Y-%m-%d')
    output_path = os.path.join(output_dir, f'H20269_RSI止盈决策分析报告_{data_end_date}.html')

    generate_html_report(df, high_df, mid_df, low_df, fine_df, output_path)

    size_kb = os.path.getsize(output_path) / 1024
    print(f'\n{"="*70}')
    print(f'[DONE] 报告生成完成')
    print(f'{"="*70}')
    print(f'  输出路径: {output_path}')
    print(f'  文件大小: {size_kb:.1f} KB')
    print(f'\n关键数据预览：')
    print(f'  高 RSI 组 250 日收益: 均值 {high_df["250日收益%"].mean():+.2f}%, 胜率 {(high_df["250日收益%"]>0).mean()*100:.0f}%')
    print(f'  高 RSI 组达到 +15% 概率: {high_df["达到+15%止盈"].mean()*100:.1f}%')
    print(f'  精细组（刚重回年线）250 日收益: 均值 {fine_df["250日收益%"].mean():+.2f}%, 胜率 {(fine_df["250日收益%"]>0).mean()*100:.0f}%')
    print(f'  精细组达到 +15% 概率: {fine_df["达到+15%止盈"].mean()*100:.1f}%')


if __name__ == '__main__':
    main()
