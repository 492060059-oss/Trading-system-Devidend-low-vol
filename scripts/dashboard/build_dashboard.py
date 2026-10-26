# -*- coding: utf-8 -*-
"""
每日指标看板生成器（手机友好，静态 HTML，供 GitHub Pages 发布）

读取：
  data/H20269历史数据.csv   红利低波全收益指数（中证官网API维护，只追加）
  data/512890行情数据.csv   红利低波ETF前复权（东财/腾讯API维护，全量刷新）
输出：
  docs/index.html  —— GitHub Pages 从 main 分支 /docs 目录发布本文件

内容：双标的的 年线乖离率（含策略区间条）、RSI6/12/24、MA20/60/120/250、
近20日明细，以及三个经历史检验的中期止盈信号状态灯（定义见页脚）。

用法：python scripts/dashboard/build_dashboard.py（先运行 update_data.py）
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
from datetime import datetime, timedelta, timezone

import pandas as pd
import plotly.graph_objects as go

OUT_PATH = 'docs/index.html'

# 策略/信号阈值（与 core/rolling_position_backtest.py 及 docs/ROLLING_POSITION_STRATEGY.md 对齐）
TIER3, TIER2 = -8.0, -4.0        # 深度定投 3×/2× 触发线（乖离率%）
SELL_A, SELL_B = 15.0, 17.5      # 年线策略 卖出50%/清仓线（乖离率%）
WATCH = 4.5                      # 中期止盈观察区（从年线下方反弹至 +4.5%）
BAR_MIN, BAR_MAX = -12.0, 20.0   # 区间条的显示范围（乖离率%）

if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def beijing_now():
    return datetime.now(timezone(timedelta(hours=8)))


# ------------------------------------------------------------- 指标计算 ----

def compute_indicators(df):
    """与 core/data_calculator.py 同口径：MA/乖离率/RSI(Wilder)。"""
    df = df.sort_values('日期').reset_index(drop=True).copy()
    for w in (20, 60, 120, 250):
        df[f'MA{w}'] = df['收盘'].rolling(w).mean()
    df['乖离率'] = (df['收盘'] - df['MA250']) / df['MA250'] * 100
    df['bias20'] = (df['收盘'] - df['MA20']) / df['MA20'] * 100
    for n in (6, 12, 24):
        delta = df['收盘'].diff()
        gain = delta.clip(lower=0).ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
        loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
        rs = gain / loss.clip(lower=1e-6)
        df[f'RSI{n}'] = (100 - 100 / (1 + rs)).clip(0.01, 99.99)
    return df


def compute_signals(df):
    """三个中期止盈信号 + 观察区（2026-10 历史检验定义，见 docs/DASHBOARD_GUIDE.md）。"""
    s = pd.DataFrame(index=df.index)
    rsi6_max15 = df['RSI6'].rolling(15).max()
    # S1 RSI6顶背离：收盘≈20日新高，且15日内RSI6曾>=78，当前RSI6低于该高点8点以上
    s['S1'] = ((df['收盘'] >= df['收盘'].rolling(20).max() * 0.999)
               & (rsi6_max15.shift(1) >= 78)
               & (df['RSI6'] <= rsi6_max15.shift(1) - 8))
    # S2 RSI6超买回落：12日内RSI6曾>=80，当前自60上方跌破60
    s['S2'] = ((df['RSI6'].shift(1) >= 60) & (df['RSI6'] < 60)
               & (df['RSI6'].rolling(12).max().shift(1) >= 80))
    # S3 跌破MA20确认：反弹情景(90日内乖离率曾<0)且10日内乖离率曾>=4%，收盘跌破MA20
    s['S3'] = ((df['收盘'].shift(1) >= df['MA20'].shift(1)) & (df['收盘'] < df['MA20'])
               & (df['乖离率'].rolling(10).max() >= 4.0)
               & (df['乖离率'].rolling(90).min() < 0))
    # S4 中期止盈观察区：从年线下方(90日内曾<0)反弹，当前乖离率>=+4.5%
    s['S4'] = (df['乖离率'] >= WATCH) & (df['乖离率'].rolling(90).min() < 0)
    return s


def last_fire(sig_series, df, within_days=(5, 15)):
    """返回 (状态: active/warm/off, 最近触发日期文本)。"""
    idx = sig_series.fillna(False).values
    last_i = None
    for i in range(len(idx) - 1, -1, -1):
        if idx[i]:
            last_i = i
            break
    if last_i is None:
        return 'off', '—'
    age = len(idx) - 1 - last_i
    state = 'active' if age <= within_days[0] else ('warm' if age <= within_days[1] else 'off')
    return state, df['日期'].iloc[last_i].strftime('%Y-%m-%d')


def zone_of(bias):
    """年线策略分区。"""
    if bias <= TIER3:
        return '深度定投3×区', 'z3x'
    if bias <= TIER2:
        return '深度定投2×区', 'z2x'
    if bias < 0:
        return '年线下方 · 定投观察', 'zbelow'
    if bias < SELL_A:
        return '年线上方 · 持有', 'zhold'
    if bias <= SELL_B:
        return '触发卖出50%线', 'zsell'
    return '触发清仓线', 'zclear'


# ------------------------------------------------------------- 图表 ----

def fig_price(df, title):
    d = df.tail(500)
    fig = go.Figure()
    below = d['收盘'] < d['MA250']
    # 跌破年线区间底纹
    in_seg, seg_start = False, None
    for i in range(len(d)):
        if below.iloc[i] and not in_seg:
            in_seg, seg_start = True, d['日期'].iloc[i]
        if (not below.iloc[i] or i == len(d) - 1) and in_seg:
            fig.add_vrect(x0=seg_start, x1=d['日期'].iloc[i], fillcolor='rgba(200,60,60,0.10)',
                          line_width=0, annotation_text='跌破年线', annotation_font_size=9,
                          annotation_font_color='#c0392b')
            in_seg = False
    for col, color, width in [('MA20', '#ff7f0e', 1.2), ('MA60', '#2ca02c', 1.2),
                              ('MA250', '#d62728', 1.6)]:
        fig.add_scatter(x=d['日期'], y=d[col], name=col, line=dict(color=color, width=width))
    fig.add_scatter(x=d['日期'], y=d['收盘'], name='收盘', line=dict(color='#1f77b4', width=1.8))
    fig.update_layout(title=title, height=330, margin=dict(l=40, r=16, t=42, b=30),
                      legend=dict(orientation='h', y=1.02, x=0, font_size=10),
                      hovermode='x unified')
    fig.update_yaxes(tickformat='.4~s')
    return fig.to_html(full_html=False, include_plotlyjs=False,
                       config={'responsive': True, 'displayModeBar': False})


def fig_bias(df, title):
    d = df.tail(1250).dropna(subset=['乖离率'])
    fig = go.Figure()
    fig.add_scatter(x=d['日期'], y=d['乖离率'], name='年线乖离率%',
                    line=dict(color='#636efa', width=1.6), fill='tozeroy',
                    fillcolor='rgba(99,110,250,0.10)')
    specs = [(TIER3, '#2980b9', '3×定投'), (TIER2, '#5dade2', '2×定投'),
             (0, '#7f8c8d', '年线'), (WATCH, '#f39c12', '止盈观察'),
             (SELL_A, '#e67e22', '卖50%'), (SELL_B, '#c0392b', '清仓')]
    for y, color, text in specs:
        fig.add_hline(y=y, line_dash='dot', line_color=color, line_width=1,
                      annotation_text=text, annotation_font_size=9,
                      annotation_font_color=color, annotation_position='right')
    fig.update_layout(title=title, height=300, margin=dict(l=40, r=52, t=42, b=30),
                      showlegend=False, hovermode='x unified')
    return fig.to_html(full_html=False, include_plotlyjs=False,
                       config={'responsive': True, 'displayModeBar': False})


def fig_rsi(df, title):
    d = df.tail(250)
    fig = go.Figure()
    for col, color in [('RSI6', '#e74c3c'), ('RSI12', '#27ae60'), ('RSI24', '#8e44ad')]:
        fig.add_scatter(x=d['日期'], y=d[col], name=col, line=dict(color=color, width=1.4))
    for y, color in [(30, '#7f8c8d'), (70, '#7f8c8d')]:
        fig.add_hline(y=y, line_dash='dot', line_color=color, line_width=1)
    fig.update_layout(title=title, height=260, margin=dict(l=40, r=16, t=42, b=30),
                      legend=dict(orientation='h', y=1.02, x=0, font_size=10),
                      hovermode='x unified', yaxis_range=[0, 100])
    return fig.to_html(full_html=False, include_plotlyjs=False,
                       config={'responsive': True, 'displayModeBar': False})


# ------------------------------------------------------------- 页面 ----

CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
       background: #f4f6f8; color: #2c3e50; padding-bottom: 40px; }
.wrap { max-width: 780px; margin: 0 auto; padding: 14px; }
h1 { font-size: 20px; margin: 8px 0 2px; }
.meta { font-size: 12px; color: #7f8c8d; margin-bottom: 10px; }
h2 { font-size: 16px; margin: 22px 0 10px; padding: 8px 12px; background: #2c3e50;
     color: #fff; border-radius: 8px; }
h2 small { font-weight: normal; opacity: .8; font-size: 12px; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
         gap: 8px; margin: 10px 0; }
.card { background: #fff; border-radius: 10px; padding: 10px 12px;
        box-shadow: 0 1px 3px rgba(0,0,0,.08); }
.card .k { font-size: 11px; color: #95a5a6; margin-bottom: 4px; }
.card .v { font-size: 19px; font-weight: 600; }
.card .v small { font-size: 11px; color: #95a5a6; font-weight: normal; }
.badge { display: inline-block; font-size: 11px; padding: 2px 8px; border-radius: 10px;
         color: #fff; margin-top: 4px; }
.z3x{background:#21618c}.z2x{background:#2e86c1}.zbelow{background:#ca8a04}
.zhold{background:#1e8449}.zsell{background:#d35400}.zclear{background:#922b21}
.zonebar { position: relative; height: 16px; border-radius: 8px; margin: 18px 2px 26px;
  background: linear-gradient(90deg,#21618c 0%,#2e86c1 12.5%,#ca8a04 25%,#1e8449 43.75%,
              #d35400 84.4%,#922b21 100%); }
.zonebar .pin { position: absolute; top: -22px; transform: translateX(-50%);
  font-size: 15px; color: #2c3e50; }
.zonebar .cur { position: absolute; top: 22px; transform: translateX(-50%);
  font-size: 11px; color: #2c3e50; white-space: nowrap; font-weight: 600; }
.zonebar .tick { position: absolute; top: 16px; font-size: 9px; color: #7f8c8d;
  transform: translateX(-50%); }
.sig { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
       gap: 8px; margin: 10px 0 4px; }
.sigcard { background: #fff; border-radius: 10px; padding: 9px 12px;
           box-shadow: 0 1px 3px rgba(0,0,0,.08); border-left: 4px solid #bdc3c7; }
.sigcard.active { border-left-color: #e74c3c; background: #fdf0ef; }
.sigcard.warm { border-left-color: #f39c12; background: #fef9f0; }
.sigcard .t { font-size: 12px; font-weight: 600; }
.sigcard .d { font-size: 11px; color: #7f8c8d; margin-top: 3px; }
.dot { display: inline-block; width: 9px; height: 9px; border-radius: 50%;
       margin-right: 5px; background: #bdc3c7; }
.active .dot { background: #e74c3c; animation: blink 1.2s infinite; }
.warm .dot { background: #f39c12; }
@keyframes blink { 50% { opacity: .35; } }
.chart { background: #fff; border-radius: 10px; padding: 6px 4px; margin: 10px 0;
         box-shadow: 0 1px 3px rgba(0,0,0,.08); }
table { width: 100%; border-collapse: collapse; background: #fff; border-radius: 10px;
        overflow: hidden; font-size: 12px; margin: 10px 0;
        box-shadow: 0 1px 3px rgba(0,0,0,.08); }
th, td { padding: 6px 8px; text-align: right; }
th:nth-child(1), td:nth-child(1), th:last-child, td:last-child { text-align: left; }
th { background: #ecf0f1; font-weight: 600; }
tr:nth-child(even) td { background: #fafbfc; }
.pos { color: #c0392b; } .neg { color: #1e8449; }
.foot { font-size: 12px; color: #7f8c8d; line-height: 1.7; margin-top: 20px;
        background: #fff; border-radius: 10px; padding: 12px 14px;
        box-shadow: 0 1px 3px rgba(0,0,0,.08); }
.foot b { color: #2c3e50; }
"""

ZONE_TICKS = [(TIER3, '-8'), (TIER2, '-4'), (0, '0'), (WATCH, '+4.5'),
              (SELL_A, '+15'), (SELL_B, '+17.5')]


def pos_pct(bias):
    return max(0.0, min(100.0, (bias - BAR_MIN) / (BAR_MAX - BAR_MIN) * 100))


def section(df, name, subtitle, is_index):
    sig = compute_signals(df)
    last = df.iloc[-1]
    bias = last['乖离率']
    zone_name, zone_cls = zone_of(bias)
    p = pos_pct(bias)

    cards = f"""
    <div class="cards">
      <div class="card"><div class="k">最新收盘</div>
        <div class="v">{last['收盘']:,.2f}<small> {last['日期'].strftime('%m-%d')}</small></div></div>
      <div class="card"><div class="k">年线乖离率</div>
        <div class="v" class="{'pos' if bias>0 else 'neg'}">{bias:+.2f}%</div>
        <span class="badge {zone_cls}">{zone_name}</span></div>
      <div class="card"><div class="k">RSI 6 / 12 / 24</div>
        <div class="v">{last['RSI6']:.0f}<small> / </small>{last['RSI12']:.0f}<small> / </small>{last['RSI24']:.0f}</div></div>
      <div class="card"><div class="k">距 MA20 / MA60</div>
        <div class="v">{last['bias20']:+.1f}%<small> / </small>
        {(last['收盘']/last['MA60']-1)*100:+.1f}%</div></div>
    </div>"""

    ticks = ''.join(f'<span class="tick" style="left:{pos_pct(v):.1f}%">{t}</span>'
                    for t, v in [(t, v) for v, t in ZONE_TICKS])
    zonebar = f"""
    <div class="zonebar">
      <span class="pin" style="left:{p:.1f}%">▼</span>
      <span class="cur" style="left:{p:.1f}%">{bias:+.2f}%</span>
      {ticks}
    </div>"""

    defs = [('S1', 'RSI6 顶背离'), ('S2', 'RSI6 超买回落'), ('S3', '跌破MA20确认')]
    sigcards = ''
    for key, label in defs:
        state, date = last_fire(sig[key], df)
        state_cn = {'active': '● 触发中（近5日）', 'warm': '○ 近期出现', 'off': '— 未触发'}[state]
        sigcards += (f'<div class="sigcard {state}"><div class="t"><span class="dot"></span>'
                     f'{label}</div><div class="d">{state_cn} · 最近 {date}</div></div>')
    s4_state, s4_date = last_fire(sig['S4'], df)
    s4_now = '● 已进入观察区' if bool(sig['S4'].iloc[-1]) else '— 未处于观察区'
    sigcards += (f'<div class="sigcard {"active" if bool(sig["S4"].iloc[-1]) else ""}">'
                 f'<div class="t"><span class="dot"></span>中期止盈观察区</div>'
                 f'<div class="d">{s4_now} · 最近进入 {s4_date}</div></div>')

    ref = '' if is_index else '<small>（ETF，阈值仅供参照）</small>'
    head = f'<h2>{name} <small>{subtitle}</small> {ref}</h2>'

    tail20 = df.tail(20).iloc[::-1]
    rows = ''
    for _, r in tail20.iterrows():
        fired = [k for k in ('S1', 'S2', 'S3') if sig[k].loc[r.name]]
        rows += (f"<tr><td>{r['日期'].strftime('%Y-%m-%d')}</td>"
                 f"<td>{r['收盘']:,.2f}</td>"
                 f"<td class=\"{'pos' if r['乖离率']>0 else 'neg'}\">{r['乖离率']:+.2f}</td>"
                 f"<td>{r['RSI6']:.0f}</td><td>{r['RSI12']:.0f}</td>"
                 f"<td>{'+'.join(fired) if fired else ''}</td></tr>")
    table = (f'<table><tr><th>日期</th><th>收盘</th><th>乖离率%</th><th>RSI6</th>'
             f'<th>RSI12</th><th>信号</th></tr>{rows}</table>')

    return (head + cards + zonebar +
            '<div class="sig">' + sigcards + '</div>' +
            f'<div class="chart">{fig_price(df, "价格与均线（近2年）")}</div>'
            f'<div class="chart">{fig_bias(df, "年线乖离率（近5年）")}</div>'
            f'<div class="chart">{fig_rsi(df, "RSI（近1年）")}</div>' +
            table)


FOOT = """
<div class="foot">
<b>口径与信号定义</b><br>
· 年线乖离率 = (收盘 − MA250) / MA250 × 100%；RSI 为 Wilder 平滑（与本项目 core/data_calculator.py 同口径）。<br>
· 策略区间：≤−8% 深度定投3×；−8%~−4% 深度定投2×；<0 年线下方；0~+15% 持有；>+15% 卖出50%；>+17.5% 清仓（年线主策略）。<br>
· S1 顶背离：收盘创20日新高而 15 日内 RSI6 高点(≥78)回落 8 点以上；S2 超买回落：12 日内 RSI6 曾≥80 后跌破 60；
S3 破位确认：反弹情景下（90 日内乖离率曾<0、10 日内曾≥+4%）收盘跌破 MA20；观察区：自年线下方反弹至 ≥+4.5%。<br>
· 历史检验（H20269，2007–2026，18 次独立事件）：自年线下方反弹至 +4.5% 后，61% 最终先触及 +15% 卖出线，
仅 2015-11、2022-11 两次直接回落——中期信号宜作<b>分批减仓/停止加仓</b>参考，不宜全仓了结。详见 docs/DASHBOARD_GUIDE.md。<br>
· 数据源：中证指数官网 API（H20269，收盘后更新）；东方财富/腾讯行情（512890 前复权）。<br>
· 本页为研究工具，不构成投资建议。
</div>
"""


def assemble_html(idx, etf, source_note=''):
    """把两个标的的指标 DataFrame 组装成完整看板 HTML（静态构建与实时渲染共用）。"""
    for df, name in [(idx, 'H20269'), (etf, '512890')]:
        if df['MA250'].iloc[-1] != df['MA250'].iloc[-1]:  # NaN 检查
            raise RuntimeError(f'{name}: 最新一日 MA250 为空，数据不足')
    now = beijing_now()
    asof = max(idx['日期'].iloc[-1], etf['日期'].iloc[-1]).strftime('%Y-%m-%d')
    note = f' · {source_note}' if source_note else ''
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>红利低波 · 每日指标看板</title>
<style>{CSS}</style>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
</head>
<body>
<div class="wrap">
<h1>红利低波 · 每日指标看板</h1>
<div class="meta">数据截至 {asof} 收盘 · 生成于 {now.strftime('%Y-%m-%d %H:%M')}（北京时间）{note}</div>
{section(idx, 'H20269', '红利低波全收益指数（主策略标的）', True)}
{section(etf, '512890', '红利低波ETF（前复权）', False)}
{FOOT}
</div>
</body>
</html>"""


def main():
    idx = compute_indicators(pd.read_csv('data/H20269历史数据.csv', encoding='utf-8-sig'))
    idx['日期'] = pd.to_datetime(idx['日期'])
    etf = compute_indicators(pd.read_csv('data/512890行情数据.csv', encoding='utf-8-sig'))
    etf['日期'] = pd.to_datetime(etf['日期'])
    html = assemble_html(idx, etf)
    with open(OUT_PATH, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'已生成 {OUT_PATH}（{len(html)/1024:.0f} KB）')
    print(f'H20269 乖离率 {idx["乖离率"].iloc[-1]:+.2f}% | '
          f'RSI6 {idx["RSI6"].iloc[-1]:.1f} | 512890 乖离率 {etf["乖离率"].iloc[-1]:+.2f}%')


if __name__ == '__main__':
    main()
