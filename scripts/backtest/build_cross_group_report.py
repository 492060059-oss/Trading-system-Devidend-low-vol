#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""横向统计报告生成器：21 组回测 × 全量指标 + 分阶段跑赢/跑输明细

替代 output/backtests/comparisons/ 下原有的 3 份汇总 md + 3 份 html：
  - 512890_ETF跟踪能力测试汇总.md/html
  - H20269_扩展测试汇总.md/html
  - 跨起始日对比.md/html
原有产物的问题：
  1. 三份 md 各覆盖一部分组（3 / 10 / 5），互相割裂，无法横向比较；
  2. 都只对满仓指数报超额，没有同仓位混合基准 → 无法区分"择时"与"低仓位"；
  3. 跨起始日对比.html 的子图②把【同一条 H20269 价格序列】按三个起点各自
     归一化后并排画，已实测三组重叠区间收盘价逐日绝对差 = 0.0000000000，
     即该子图不含任何新信息（详见 docs/progress.md 0.24 节）。

本脚本的取舍：
  - 指标【不重新实现】，一律 import RollingPositionBacketst / PerformanceAnalyzer
    复用，避免公式二次漂移（A/B/E/F/G/H/J 等修复过的口径必须单一来源）。
  - 阶段定义直接用 MARKET_PHASES（绝对日历日期），因此对任何起始日、
    任何标的（H20269 / 512890）都可套用；每组只统计与自身数据区间相交的阶段。

用法：
    python scripts/build_cross_group_report.py
"""

# === PROJECT-ROOT BOOTSTRAP ===
import os as _os
import sys as _sys
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
for _p in (_ROOT, _os.path.join(_ROOT, 'core')):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)
if _os.path.abspath(_os.getcwd()) != _ROOT:
    _os.chdir(_ROOT)
# === /PROJECT-ROOT BOOTSTRAP ===

import io
import os
import sys

import pandas as pd

if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

from rolling_position_backtest import RollingPositionBacktest
from performance_analysis import PerformanceAnalyzer, MARKET_PHASES

OUT_MD = 'output/backtests/横向统计报告.md'
OUT_CSV = 'output/backtests/横向统计_指标总表.csv'
OUT_PHASE_CSV = 'output/backtests/横向统计_分阶段明细.csv'
OUT_HTML = 'output/backtests/横向统计_超额曲线对比.html'

# 阶段判定口径（两处坑，实测撞到过，勿删注释）：
#   TOL —— 超额恰好为 0 必须记「持平」，不能记「跑输」。512890 有 4 组在
#          「924行情」整段满仓持有，策略 17.51% vs 基准 17.51%，超额 = ±0.00pp。
#          那是完美跟踪，把它算成跑输会凭空压低 ETF 胜率（曾误报 5/15）。
#   MIN_DAYS —— 交易日过短的阶段是【冷启动残片】而非策略表现：某组起始日落在
#          阶段末尾，只剩 1~3 个交易日，此时仓位还在 0~2.5%（定投刚开始建仓），
#          必然跟不上指数。这类阶段单独标注并从主胜率中剔除，但**照常列出**，
#          不做静默截断。
TOL = 0.01       # pp，小于此绝对值视为持平
MIN_DAYS = 20    # 交易日，少于此视为冷启动残片

H = 'output/backtests/h20269'
E = 'output/backtests/etf512890'

# (输出目录, 标的, 起始日, 初始资金, 特征标签, 来源脚本)
# 与各 run_*.py 的 CONFIGS 保持一致；参数差异只有 initial_capital 一项。
GROUPS = [
    # ---- run_multiple_backtests.py（3 组）----
    (f'{H}/2016-01起_深度定投策略', 'H20269', '2016-01-01', 100000, '主组', 'run_multiple'),
    (f'{H}/2018-01起_深度定投策略', 'H20269', '2018-01-01', 100000, '主组', 'run_multiple'),
    (f'{H}/2020-01起_深度定投策略', 'H20269', '2020-01-01', 100000, '主组', 'run_multiple'),
    # ---- run_extended_backtests.py（10 组）----
    (f'{H}/2014-07-08起_牛市启动前', 'H20269', '2014-07-08', 100000, '牛市启动前', 'extended'),
    (f'{H}/2015-06-12起_5178牛市顶', 'H20269', '2015-06-12', 100000, '5178牛市顶', 'extended'),
    (f'{H}/2015-09-15起_股灾底2.0', 'H20269', '2015-09-15', 100000, '股灾底2.0', 'extended'),
    (f'{H}/2017-11-13起_蓝筹慢牛顶', 'H20269', '2017-11-13', 100000, '蓝筹慢牛顶', 'extended'),
    (f'{H}/2018-12-28起_贸易战熊底', 'H20269', '2018-12-28', 100000, '贸易战熊底', 'extended'),
    (f'{H}/2019-07-01起_震荡市', 'H20269', '2019-07-01', 100000, '震荡市', 'extended'),
    (f'{H}/2021-09-13起_红利阶段顶', 'H20269', '2021-09-13', 100000, '红利阶段顶', 'extended'),
    (f'{H}/2022-04-27起_疫情底', 'H20269', '2022-04-27', 100000, '疫情底', 'extended'),
    (f'{H}/2023-05-09起_红利顶', 'H20269', '2023-05-09', 100000, '红利顶', 'extended'),
    (f'{H}/2024-09-23起_924前夕', 'H20269', '2024-09-23', 100000, '924前夕', 'extended'),
    # ---- run_orphan_backtests.py（3 组）----
    (f'{H}/2015-05起_深度定投策略', 'H20269', '2015-05-01', 100000, '深度定投', 'orphan'),
    (f'{H}/2015-05起_含交易成本', 'H20269', '2015-05-01', 100000, '含成本(与上组同参)', 'orphan'),
    (f'{H}/2026-05起_50万本金', 'H20269', '2026-05-07', 500000, '50万本金', 'orphan'),
    # ---- run_512890_backtests.py（5 组）----
    (f'{E}/2020-02-03起_疫情底', '512890', '2020-02-03', 100000, '疫情底', 'etf'),
    (f'{E}/2021-09-13起_红利阶段顶', '512890', '2021-09-13', 100000, '红利阶段顶', 'etf'),
    (f'{E}/2022-04-27起_疫情底2', '512890', '2022-04-27', 100000, '疫情底2', 'etf'),
    (f'{E}/2023-05-09起_红利顶', '512890', '2023-05-09', 100000, '红利顶', 'etf'),
    (f'{E}/2024-09-23起_924前夕', '512890', '2024-09-23', 100000, '924前夕', 'etf'),
]


def run_group(symbol, start_date, capital):
    """重跑一组回测，取回 metrics（不落盘，避免污染既有产物）"""
    bt = RollingPositionBacktest(
        csv_file_path=f'data/{symbol}历史数据.csv',
        invest_days=40,
        sell_threshold_a=15.0,
        sell_threshold_b=17.5,
        cash_return_rate=1.2,
        initial_capital=capital,
        start_date=start_date,
        end_date=None,
        dca_tiers=None,
    )
    bt.load_data()
    bt.run_backtest()
    return bt.calculate_metrics()


def phase_detail(daily_csv):
    """复用 PerformanceAnalyzer 的阶段口径（含 Bug F 覆盖率断言）"""
    pa = PerformanceAnalyzer(daily_csv)
    return pa.analyze_phases(), pa.df


def classify(excess_pp, days):
    """→ ('跑赢'|'跑输'|'持平', 是否为有效阶段)"""
    valid = days >= MIN_DAYS
    if abs(excess_pp) < TOL:
        return '持平', valid
    return ('跑赢' if excess_pp > 0 else '跑输'), valid


def fmt(v, nd=2, plus=False):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return '—'
    s = f'{v:+.{nd}f}' if plus else f'{v:.{nd}f}'
    return s


def main():
    rows = []
    phase_rows = []
    curves = {}

    for out_dir, symbol, start, cap, feat, src in GROUPS:
        # ⚠️ 组名必须带标的前缀：basename 在两个标的间会撞名。
        # 实测撞名 3 对：2021-09-13起_红利阶段顶 / 2023-05-09起_红利顶 /
        # 2024-09-23起_924前夕 —— h20269 与 etf512890 下同名目录各一份。
        # 若只用 basename 做 key，会造成三处静默错误：
        #   ① 分阶段矩阵 pivot(aggfunc='first') 只保留先到的那组，512890 行显示成 H20269 的值；
        #   ② 每组细目 filter 命中两组，阶段表凭空多出重复行；
        #   ③ curves dict 后写覆盖先写，超额曲线图少画 3 条（18 条冒充 21 条）。
        gid = f'{symbol}/{os.path.basename(out_dir)}'
        gname = os.path.basename(out_dir)
        daily_csv = os.path.join(out_dir, f'{symbol}_滚动仓位每日记录.csv')
        if not os.path.exists(daily_csv):
            raise FileNotFoundError(
                f'缺少每日记录: {daily_csv}\n'
                f'  请先运行对应脚本生成该组产物（scripts/run_*.py）。\n'
                f'  本报告【拒绝跳过缺失组】—— 静默少统计一组，会让"21 组"变成谎话。')

        print(f'  [{src:12}] {gid}')
        m = run_group(symbol, start, cap)
        pdf, ddf = phase_detail(daily_csv)

        # 一致性闸门：指标来自【本次重跑】，阶段来自【磁盘上的每日记录】。
        # 若磁盘产物是旧版本代码生成的，两者会来自不同 vintage，报告就成了拼接。
        disk_cum = (ddf['总资产'].iloc[-1] / cap - 1) * 100
        if abs(disk_cum - m['策略累计收益率']) > 1e-6:
            raise AssertionError(
                f'{out_dir}: vintage 不一致 —— 重跑累计 {m["策略累计收益率"]:.6f}% '
                f'vs 磁盘每日记录末值推算 {disk_cum:.6f}%（差 '
                f'{disk_cum - m["策略累计收益率"]:+.6f} pp）。\n'
                f'  说明磁盘产物由旧代码生成，请先重跑对应 scripts/run_*.py 再生成本报告。')

        # 逐阶段判定（含持平口径与冷启动残片标记）
        marks = [classify(r['超额阶段收益%'], r['交易日数']) for _, r in pdf.iterrows()]
        win = sum(1 for j, v in marks if v and j == '跑赢')
        lose = sum(1 for j, v in marks if v and j == '跑输')
        flat = sum(1 for j, v in marks if v and j == '持平')
        n_valid = win + lose + flat
        n_frag = sum(1 for _, v in marks if not v)

        rows.append({
            '组ID': gid, '组': gname, '标的': symbol, '起始日': start,
            '特征': feat, '来源': src, '初始资金': cap,
            '交易日': m['回测天数'], '年数': m['回测年数'],
            '策略累计%': m['策略累计收益率'], '策略年化%': m['策略年化收益率'],
            '策略回撤%': m['策略最大回撤'], '策略波动%': m['策略年化波动率'],
            '策略夏普': m['策略夏普比率'], '策略索提诺': m['策略索提诺比率'],
            '策略卡尔马': m['策略卡尔马比率'],
            '满仓指数累计%': m['基准累计收益率'], '满仓指数年化%': m['基准年化收益率'],
            '满仓指数回撤%': m['基准最大回撤'], '满仓指数夏普': m['基准夏普比率'],
            'vs满仓超额累计%': m['超额收益(累计)'], 'vs满仓超额年化%': m['超额收益(年化)'],
            '混合权重w%': m['混合基准权重%'],
            '混合累计%': m['混合基准累计收益率'], '混合年化%': m['混合基准年化收益率'],
            '混合回撤%': m['混合基准最大回撤'], '混合夏普': m['混合基准夏普比率'],
            '混合索提诺': m['混合基准索提诺比率'],
            '择时超额累计%': m['择时超额(累计)'], '择时超额年化%': m['择时超额(年化)'],
            '择时夏普差': m['择时夏普差'],
            '回撤差vs满仓pp': abs(m['基准最大回撤']) - abs(m['策略最大回撤']),
            '回撤差vs混合pp': abs(m['混合基准最大回撤']) - abs(m['策略最大回撤']),
            '交易次数': m['交易次数'], '总交易成本': m['总交易成本'],
            '实际佣金率%': m['实际佣金率%'],
            '阶段数': len(pdf), '有效阶段数': n_valid, '冷启动残片': n_frag,
            '阶段跑赢': win, '阶段跑输': lose, '阶段持平': flat,
        })

        for (judge, valid), (_, r) in zip(marks, pdf.iterrows()):
            phase_rows.append({
                '组ID': gid, '组': gname, '标的': symbol, '起始日': start,
                '阶段': r['阶段'], '时间段': r['时间段'], '交易日': r['交易日数'],
                '策略%': r['策略阶段收益%'], '基准%': r['基准阶段收益%'],
                '超额pp': r['超额阶段收益%'],
                '策略回撤%': r['策略最大回撤%'], '基准回撤%': r['基准最大回撤%'],
                '仓位中位%': r['仓位中位数%'],
                '买': r['买入操作'], '卖': r['卖出操作'],
                '判定': judge, '有效': valid,
            })

        # 超额曲线（策略 − 满仓指数，各自归一化起点）
        curves[gid] = (
            ddf['日期'].tolist(), ddf['相对收益%'].tolist(), symbol)

    df = pd.DataFrame(rows)
    pdf_all = pd.DataFrame(phase_rows)
    df.to_csv(OUT_CSV, index=False, encoding='utf-8-sig')
    pdf_all.to_csv(OUT_PHASE_CSV, index=False, encoding='utf-8-sig')
    print(f'\n  指标总表  -> {OUT_CSV}  ({len(df)} 组)')
    print(f'  分阶段明细 -> {OUT_PHASE_CSV}  ({len(pdf_all)} 行)')

    write_md(df, pdf_all)
    write_html(curves, len(df))


def write_md(df, pdf_all):
    h = df[df['标的'] == 'H20269']
    e = df[df['标的'] == '512890']

    with io.open(OUT_MD, 'w', encoding='utf-8') as f:
        w = f.write
        w('# 横向统计报告：21 组回测全量指标 + 分阶段归因\n\n')
        w(f'**生成脚本**：`scripts/build_cross_group_report.py`　'
          f'**组数**：{len(df)}（H20269 {len(h)} + 512890 {len(e)}）　'
          f'**阶段行数**：{len(pdf_all)}\n\n')

        w('> **两个基准的分工（读表前必读）**\n>\n')
        w('> - `满仓指数` = 100% 仓位持有指数。策略平均仓位只有 w%，两者**风险暴露不对等**，\n')
        w('>   差额里混了"没满仓"带来的现金拖累与回撤削减。\n')
        w('> - `同仓位混合` = w% 指数 + (1−w%) 现金、每日再平衡。与策略**暴露对等**。\n>\n')
        w('> ```\n')
        w('> 策略 − 满仓指数  = 择时贡献 + 现金拖累\n')
        w('> 策略 − 同仓位混合 = 择时贡献        ← 这才是策略的真实增加值\n')
        w('> ```\n>\n')
        w('> 回撤同理：`回撤差vs满仓` 含仓位效应，`回撤差vs混合` 才是择时对回撤的净影响。\n\n')

        n_frag_all = int(df['冷启动残片'].sum())
        n_flat_all = int(df['阶段持平'].sum())
        w('> **阶段判定口径**\n>\n')
        w(f'> - 超额绝对值 < {TOL} pp 记 **持平**（不计入跑赢也不计入跑输）。'
          f'全样本 {n_flat_all} 例，均为满仓持有、与指数完美跟踪所致。\n')
        w(f'> - 交易日 < {MIN_DAYS} 的阶段记 **冷启动残片**：该组起始日恰落在阶段末尾，'
          f'仓位尚在 0~3%\n>   建仓期，跟不上指数属机制必然而非策略判断。'
          f'全样本 {n_frag_all} 例，表中以 `※` 标注，\n>   **照常列出但不计入胜率**。\n\n')

        # ============ 1. 主表 ============
        w('## 1. 总表：收益与风险（全 21 组）\n\n')
        w('| 组 | 标的 | 年数 | 策略累计% | 策略年化% | 策略回撤% | 夏普 | 索提诺 | '
          '满仓累计% | vs满仓pp | 混合w% | 混合累计% | **择时超额pp** | 择时夏普差 | '
          '回撤vs满仓 | **回撤vs混合** | 阶段 |\n')
        w('|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|\n')
        for _, r in df.iterrows():
            w(f"| {r['组']} | {r['标的']} | {r['年数']:.2f} | "
              f"**{r['策略累计%']:.2f}** | {r['策略年化%']:.2f} | {r['策略回撤%']:.2f} | "
              f"{r['策略夏普']:.3f} | {r['策略索提诺']:.3f} | "
              f"{r['满仓指数累计%']:.2f} | {r['vs满仓超额累计%']:+.2f} | "
              f"{r['混合权重w%']:.1f} | {r['混合累计%']:.2f} | "
              f"**{r['择时超额累计%']:+.2f}** | {r['择时夏普差']:+.3f} | "
              f"{r['回撤差vs满仓pp']:+.2f} | **{r['回撤差vs混合pp']:+.2f}** | "
              f"{r['阶段跑赢']}/{r['有效阶段数']} |\n")
        w('\n')

        # ============ 2. 汇总统计 ============
        w('## 2. 汇总统计\n\n')
        for label, sub in (('H20269（指数，16 组）', h), ('512890（真实 ETF，5 组）', e),
                           ('全部 21 组', df)):
            if not len(sub):
                continue
            n = len(sub)
            w_pos = int((sub['vs满仓超额累计%'] > 0).sum())
            t_pos = int((sub['择时超额累计%'] > 0).sum())
            dd_full = int((sub['回撤差vs满仓pp'] > 0).sum())
            dd_bl = int((sub['回撤差vs混合pp'] > 0).sum())
            sh = int((sub['择时夏普差'] > 0).sum())
            ph_w = int(sub['阶段跑赢'].sum())
            ph_l = int(sub['阶段跑输'].sum())
            ph_f = int(sub['阶段持平'].sum())
            ph_n = int(sub['有效阶段数'].sum())
            ph_x = int(sub['冷启动残片'].sum())
            w(f'### {label}\n\n')
            w(f'| 口径 | 结果 |\n|---|---|\n')
            w(f'| 对满仓指数正超额 | **{w_pos}/{n}** 组（均值 {sub["vs满仓超额累计%"].mean():+.2f} pp） |\n')
            w(f'| 对同仓位混合正超额（真实择时） | **{t_pos}/{n}** 组（均值 {sub["择时超额累计%"].mean():+.2f} pp） |\n')
            w(f'| 回撤比满仓更浅 | {dd_full}/{n} 组（均值 {sub["回撤差vs满仓pp"].mean():+.2f} pp） |\n')
            w(f'| **回撤比同仓位混合更浅** | **{dd_bl}/{n}** 组（均值 {sub["回撤差vs混合pp"].mean():+.2f} pp） |\n')
            w(f'| 择时夏普差为正 | {sh}/{n} 组（均值 {sub["择时夏普差"].mean():+.3f}） |\n')
            w(f'| 阶段胜率（有效阶段） | **{ph_w}/{ph_n}**（{ph_w / ph_n * 100:.1f}%）'
              f'　跑输 {ph_l}，持平 {ph_f} |\n')
            w(f'| 另有冷启动残片 | {ph_x} 例（已剔除，见口径说明） |\n\n')

        # ============ 3. 分阶段矩阵 ============
        w('## 3. 分阶段超额矩阵（组 × 阶段，单位 pp）\n\n')
        w('每格 = 该组在该阶段的 `策略阶段收益 − 基准阶段收益`。'
          '空格 = 该组数据不覆盖此阶段；`※` = 冷启动残片（不计入胜率）；'
          '`≈0` = 持平。\n\n')
        order = [p['name'] for p in MARKET_PHASES]
        piv = pdf_all.pivot_table(index='组ID', columns='阶段', values='超额pp',
                                  aggfunc='first')
        # 判定与有效性另建索引，避免 pivot 把布尔/文本聚合掉
        jud = {(r['组ID'], r['阶段']): (r['判定'], r['有效'])
               for _, r in pdf_all.iterrows()}
        assert len(piv) == len(df), (
            f'矩阵行数 {len(piv)} != 组数 {len(df)}：组名仍在撞车，会静默丢组')
        cols = [c for c in order if c in piv.columns]
        piv = piv.reindex(columns=cols)
        piv = piv.reindex([r['组ID'] for _, r in df.iterrows()])
        w('| 组 | ' + ' | '.join(cols) + ' | 跑赢/有效 |\n')
        w('|---' * (len(cols) + 2) + '|\n')
        for g, row in piv.iterrows():
            vals = []
            nw = nt = 0
            for c in cols:
                v = row[c]
                if pd.isna(v):
                    vals.append('')
                    continue
                judge, valid = jud[(g, c)]
                if not valid:
                    vals.append(f'{v:+.2f}※')
                elif judge == '持平':
                    nt += 1
                    vals.append('≈0')
                else:
                    nt += 1
                    nw += judge == '跑赢'
                    vals.append(f'**{v:+.2f}**' if judge == '跑赢' else f'{v:+.2f}')
            w(f'| {g} | ' + ' | '.join(vals) + f' | {nw}/{nt} |\n')
        w('\n')

        w('### 3.1 各阶段横向胜率（哪些行情策略擅长/不擅长）\n\n')
        w('仅统计有效阶段；`残片` 列为被剔除的冷启动阶段数。\n\n')
        w('| 阶段 | 有效组数 | 跑赢 | 跑输 | 持平 | 胜率 | 超额均值pp | 超额中位pp | 最好 | 最差 | 残片 |\n')
        w('|---|---|---|---|---|---|---|---|---|---|---|\n')
        for name in order:
            allsub = pdf_all[pdf_all['阶段'] == name]
            sub = allsub[allsub['有效']]
            if not len(sub):
                continue
            nw = int((sub['判定'] == '跑赢').sum())
            nl = int((sub['判定'] == '跑输').sum())
            nf = int((sub['判定'] == '持平').sum())
            w(f'| {name} | {len(sub)} | {nw} | {nl} | {nf} | {nw / len(sub) * 100:.0f}% | '
              f'{sub["超额pp"].mean():+.2f} | {sub["超额pp"].median():+.2f} | '
              f'{sub["超额pp"].max():+.2f} | {sub["超额pp"].min():+.2f} | '
              f'{len(allsub) - len(sub)} |\n')
        w('\n')

        # ============ 4. 每组细目 ============
        w('## 4. 每组细目\n\n')
        for _, r in df.iterrows():
            g = r['组ID']
            w(f"### {r['标的']} / {r['组']}　（起始 {r['起始日']}，"
              f"本金 {r['初始资金']:,}）\n\n")
            w(f"**特征**：{r['特征']}　**来源脚本**：`{r['来源']}`　"
              f"**区间**：{r['交易日']:.0f} 个交易日 / {r['年数']:.2f} 年\n\n")
            w('| 口径 | 累计% | 年化% | 最大回撤% | 波动% | 夏普 | 索提诺 |\n')
            w('|---|---|---|---|---|---|---|\n')
            w(f"| 策略 | **{r['策略累计%']:.2f}** | {r['策略年化%']:.2f} | "
              f"{r['策略回撤%']:.2f} | {r['策略波动%']:.2f} | "
              f"{r['策略夏普']:.3f} | {r['策略索提诺']:.3f} |\n")
            w(f"| 满仓指数 | {r['满仓指数累计%']:.2f} | {r['满仓指数年化%']:.2f} | "
              f"{r['满仓指数回撤%']:.2f} | — | {r['满仓指数夏普']:.3f} | — |\n")
            w(f"| 同仓位混合(w={r['混合权重w%']:.1f}%) | {r['混合累计%']:.2f} | "
              f"{r['混合年化%']:.2f} | {r['混合回撤%']:.2f} | — | "
              f"{r['混合夏普']:.3f} | {r['混合索提诺']:.3f} |\n\n")
            w(f"- **vs 满仓指数**：{r['vs满仓超额累计%']:+.2f} pp 累计 / "
              f"{r['vs满仓超额年化%']:+.2f} pp 年化（含现金拖累）\n")
            w(f"- **vs 同仓位混合（真实择时）**：{r['择时超额累计%']:+.2f} pp 累计 / "
              f"{r['择时超额年化%']:+.2f} pp 年化\n")
            w(f"- 回撤：比满仓 {r['回撤差vs满仓pp']:+.2f} pp，"
              f"**比同仓位混合 {r['回撤差vs混合pp']:+.2f} pp**"
              f"（负=同等暴露下策略回撤反而更深）\n")
            w(f"- 交易 {r['交易次数']:.0f} 次，总成本 {r['总交易成本']:.2f} 元，"
              f"实际佣金率 {r['实际佣金率%']:.4f}%\n\n")

            sub = pdf_all[pdf_all['组ID'] == g]
            frag_note = (f"，另有 {r['冷启动残片']:.0f} 个冷启动残片(※)不计入"
                         if r['冷启动残片'] else '')
            w(f"**分阶段（跑赢 {r['阶段跑赢']}/{r['有效阶段数']}"
              f"，跑输 {r['阶段跑输']}，持平 {r['阶段持平']}{frag_note}）**\n\n")
            w('| 阶段 | 时间段 | 交易日 | 策略% | 基准% | 超额pp | 策略回撤% | '
              '基准回撤% | 仓位中位% | 买/卖 | 判定 |\n')
            w('|---|---|---|---|---|---|---|---|---|---|---|\n')
            for _, p in sub.iterrows():
                if not p['有效']:
                    mk, tag = '※', '冷启动残片'
                elif p['判定'] == '跑赢':
                    mk, tag = '✅', '跑赢'
                elif p['判定'] == '持平':
                    mk, tag = '➖', '持平'
                else:
                    mk, tag = '❌', '跑输'
                w(f"| {p['阶段']} | {p['时间段']} | {p['交易日']} | "
                  f"{p['策略%']:.2f} | {p['基准%']:.2f} | "
                  f"{mk} **{p['超额pp']:+.2f}** | {p['策略回撤%']:.2f} | "
                  f"{p['基准回撤%']:.2f} | {p['仓位中位%']:.1f} | "
                  f"{p['买']}/{p['卖']} | {tag} |\n")
            w('\n')
            eff = sub[sub['有效']]
            if len(eff) >= 2:
                best = eff.loc[eff['超额pp'].idxmax()]
                worst = eff.loc[eff['超额pp'].idxmin()]
                w(f"- 最强阶段：**{best['阶段']}** {best['超额pp']:+.2f} pp"
                  f"（仓位中位 {best['仓位中位%']:.1f}%）\n")
                w(f"- 最弱阶段：**{worst['阶段']}** {worst['超额pp']:+.2f} pp"
                  f"（仓位中位 {worst['仓位中位%']:.1f}%）\n\n")
            elif len(eff) == 1:
                o = eff.iloc[0]
                w(f"- 仅 1 个有效阶段：**{o['阶段']}** {o['超额pp']:+.2f} pp"
                  f"（仓位中位 {o['仓位中位%']:.1f}%），不足以谈强弱分布\n\n")
            else:
                w('- 无有效阶段（区间过短，全部为冷启动残片）\n\n')

        w('---\n\n')
        w('## 5. 数据来源与复现\n\n')
        w('```bash\n')
        w('python scripts/run_multiple_backtests.py    # 3 组\n')
        w('python scripts/run_extended_backtests.py    # 10 组\n')
        w('python scripts/run_512890_backtests.py      # 5 组（ETF）\n')
        w('python scripts/run_orphan_backtests.py      # 3 组\n')
        w('python scripts/build_cross_group_report.py  # 本报告\n')
        w('```\n\n')
        w('指标口径与各组回测**完全同源**（本脚本 import `RollingPositionBacktest`\n')
        w('与 `PerformanceAnalyzer`，不另行实现任何公式）。阶段划分取 `MARKET_PHASES`\n')
        w('绝对日历区间，每组只统计与自身数据区间相交的阶段，并继承 Bug F 的覆盖率断言。\n\n')
        w('**已知重复**：`2015-05起_深度定投策略` 与 `2015-05起_含交易成本` 参数完全相同\n')
        w('（起始日、本金、成本开关一致），两组每日记录已实测逐行相同，属历史遗留的重复组。\n')

    print(f'  报告      -> {OUT_MD}')


def write_html(curves, n_groups):
    """21 组超额曲线（策略 − 满仓指数）叠加，横轴对齐真实日期"""
    import plotly.graph_objects as go
    assert len(curves) == n_groups, (
        f'超额曲线只有 {len(curves)} 条，应为 {n_groups} 条 —— key 撞车会静默覆盖曲线')
    fig = go.Figure()
    for name, (x, y, sym) in curves.items():
        fig.add_trace(go.Scatter(
            x=x, y=y, name=name, mode='lines',
            line=dict(width=1.6, dash='dot' if sym == '512890' else 'solid'),
            hovertemplate=f'<b>{name}</b><br>%{{x|%Y-%m-%d}}<br>相对满仓: %{{y:.2f}} pp<extra></extra>',
        ))
    fig.add_hline(y=0, line_dash='dash', line_color='gray', line_width=1)
    fig.update_layout(
        title='21 组超额收益曲线（策略 − 满仓指数，单位 pp；虚线 = 512890 ETF）<br>'
              '<sub>横轴为真实日期，各组起点不同故均从 0 出发；曲线上行=策略在拉开差距</sub>',
        xaxis_title='日期', yaxis_title='相对满仓指数的超额 (pp)',
        template='plotly_white', width=1500, height=850, hovermode='closest',
        legend=dict(font=dict(size=10)),
    )
    fig.write_html(OUT_HTML)
    print(f'  超额曲线  -> {OUT_HTML}')


if __name__ == '__main__':
    print('=' * 78)
    print('# 横向统计报告生成（21 组）')
    print('=' * 78)
    main()
    print('\n✅ 完成')
