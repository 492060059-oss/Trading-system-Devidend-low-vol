# -*- coding: utf-8 -*-
"""补跑「孤儿组」回测

背景：output/backtests/h20269/ 下有 3 组回测**没有任何脚本负责生成**，
是历史上手工跑出来的，因此每次修 bug 后它们都会悄悄变成旧数据 ——
2026-08-23 重跑时就发现 `2015-05起_深度定投策略` 仍是 2026-07-23 的结果
（累计 202.81% vs 当前代码 204.45%），而它恰好是 audit_checks.py 与
performance_analysis.py 的**默认引用组**。

本脚本把这 3 组纳入可重复执行的范围，消除「没人负责」的死角。

注：`2015-05起_含交易成本` 与 `2015-05起_深度定投策略` 参数已完全相同
（交易成本建模在 0.9 之后成为默认行为，不再是可选项），两组必然输出
一致的数字。保留两个目录只为不破坏历史文档里的引用路径。
"""
import os
import sys

# === PROJECT-ROOT BOOTSTRAP ===
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (_ROOT, os.path.join(_ROOT, 'core')):
    if _p not in sys.path:
        sys.path.insert(0, _p)
if os.path.abspath(os.getcwd()) != _ROOT:
    os.chdir(_ROOT)
# === /PROJECT-ROOT BOOTSTRAP ===

sys.stdout.reconfigure(encoding='utf-8')

from rolling_position_backtest import RollingPositionBacktest
from performance_analysis import PerformanceAnalyzer

CSV = 'data/H20269历史数据.csv'
H = 'output/backtests/h20269'

# (输出目录, 起始日, 初始资金)
JOBS = [
    (f'{H}/2015-05起_深度定投策略', '2015-05-01', 100000),
    (f'{H}/2015-05起_含交易成本',   '2015-05-01', 100000),
    (f'{H}/2026-05起_50万本金',     '2026-05-07', 500000),
]

for out, start, cap in JOBS:
    print(f'\n{"#" * 78}\n# {out}   起始 {start}  本金 {cap:,}\n{"#" * 78}')
    bt = RollingPositionBacktest(csv_file_path=CSV, start_date=start,
                                 initial_capital=cap)
    bt.run(output_dir=out)

    # 时间维度分析（阶段胜负表的来源）—— 调用方式与 run_multiple_backtests.py 一致
    daily = os.path.join(out, 'H20269_滚动仓位每日记录.csv')
    try:
        pa = PerformanceAnalyzer.from_backtest(daily, bt)
        pa.plot_analysis(os.path.join(out, '时间维度分析_综合可视化.html'))
        pa.generate_report(os.path.join(out, '时间维度分析报告.md'))
    except Exception as e:
        # 2026-05 组只有 60 个交易日，阶段划分可能无法成立 —— 报告但不中断
        print(f'  [WARN] 时间维度分析失败（组太短？）: {type(e).__name__}: {e}')

print('\n✅ 孤儿组补跑完成')
