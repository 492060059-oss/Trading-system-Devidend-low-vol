# -*- coding: utf-8 -*-
"""
批量运行多起始日回测 + 时间维度分析

每个起始日都会：
1. 运行完整回测（含深度定投、快照启动）
2. 生成时间维度分析（HTML 可视化 + MD 报告）

横向对比不在本脚本内生成 —— 见 scripts/backtest/build_cross_group_report.py
（21 组统一口径的横向统计报告，已取代原 comparisons/ 汇总产物）。
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
import pandas as pd
# plotly 已不再需要：本脚本的绘图职责随 comparisons 汇总一并下线

# Windows 控制台 UTF-8 输出
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

from rolling_position_backtest import RollingPositionBacktest
from performance_analysis import PerformanceAnalyzer


# ============================================================
# 三组起始日配置
# ============================================================
CONFIGS = [
    ('2016-01-01', 'output/backtests/h20269/2016-01起_深度定投策略'),
    ('2018-01-01', 'output/backtests/h20269/2018-01起_深度定投策略'),
    ('2020-01-01', 'output/backtests/h20269/2020-01起_深度定投策略'),
]

# 起始日 → 曲线颜色（用于对比图）
COLOR_MAP = {
    '2016-01-01': '#1f77b4',  # 蓝
    '2018-01-01': '#ff7f0e',  # 橙
    '2020-01-01': '#2ca02c',  # 绿
}


def run_single(start_date, output_dir):
    """运行单组回测 + 时间维度分析，返回指标字典"""
    print(f"\n{'#'*80}")
    print(f"# 起始日: {start_date}")
    print(f"# 输出目录: {output_dir}")
    print(f"{'#'*80}\n")

    # 1. 跑回测（含深度定投、快照启动、所有新功能）
    bt = RollingPositionBacktest(
        csv_file_path='data/H20269历史数据.csv',
        invest_days=40,
        sell_threshold_a=15.0,
        sell_threshold_b=17.5,
        cash_return_rate=1.2,
        initial_capital=100000,
        start_date=start_date,
        end_date=None,
        dca_tiers=None,  # 默认三档加倍
    )
    bt.run(output_dir=output_dir)

    # 2. 时间维度分析
    # from_backtest 而非裸 PerformanceAnalyzer(csv)：把 metrics 与策略参数
    # 一并带进报告 —— 原 {stock}_滚动仓位回测指标.txt 的内容已并入报告
    # （第 1 节三方对照表 / 第 6 节参数 / 第 7 节成本），该 txt 不再生成。
    daily_csv = os.path.join(output_dir, 'H20269_滚动仓位每日记录.csv')
    analyzer = PerformanceAnalyzer.from_backtest(daily_csv, bt)
    html_path = os.path.join(output_dir, '时间维度分析_综合可视化.html')
    report_path = os.path.join(output_dir, '时间维度分析报告.md')
    analyzer.plot_analysis(html_path)
    analyzer.generate_report(report_path)

    # 3. 跑一次 calculate_metrics 拿指标（用于跨起始日对比）
    metrics = bt.calculate_metrics()
    return {
        'start_date_str': start_date,
        'output_dir': output_dir,
        'metrics': metrics,
        'daily_csv': daily_csv,
    }


# ============================================================
# 跨起始日汇总已下线（2026-08-23，见 docs/progress.md 0.24）
# ------------------------------------------------------------
# 原 build_comparison_report() 在此生成 output/backtests/comparisons/
# 下的汇总 md + html。移除原因：
#   ① 三份汇总各只覆盖一部分组（3 / 10 / 5），互相割裂无法横向比较；
#   ② 都只对满仓指数报超额，缺同仓位混合基准，分不清"择时"与"低仓位"；
#   ③ html 子图②「不同起点的基准累计收益率」是同一条价格序列的多次
#      重新归一化（实测逐日绝对差 = 0.0000000000），不含新信息。
# 替代产物：python scripts/backtest/build_cross_group_report.py
#   -> 横向统计报告.md / 横向统计_指标总表.csv
#      / 横向统计_分阶段明细.csv / 横向统计_超额曲线对比.html
# ============================================================

# ============================================================
# 主流程
# ============================================================
if __name__ == '__main__':
    print("=" * 80)
    print("批量运行多起始日回测 + 时间维度分析")
    print(f"起始日列表: {[c[0] for c in CONFIGS]}")
    print("=" * 80)

    results = []
    for start_date, output_dir in CONFIGS:
        r = run_single(start_date, output_dir)
        results.append(r)


    print(f"\n{'='*80}")
    print(f"✅ 全部完成！")
    print(f"{'='*80}")
    print(f"\n每组输出目录（4 个文件）：")
    for r in results:
        print(f"  {r['output_dir']}/")
        print(f"    ├─ H20269_滚动仓位每日记录.csv")
        print(f"    ├─ H20269_滚动仓位交易记录.csv")
        print(f"    ├─ 时间维度分析_综合可视化.html")
        print(f"    └─ 时间维度分析报告.md")
    print(f"\n横向对比请运行：python scripts/backtest/build_cross_group_report.py")
    print(f"  └─ output/backtests/横向统计报告.md（21 组统一口径）")
