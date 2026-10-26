# -*- coding: utf-8 -*-
"""
H20269 扩展测试：10 个新起始日（多样化市场特征）

选起始日原则（覆盖不同乖离率/市场特征）：
- 极端顶部：2015-06-12（5178 牛市顶，乖离率 +73.35%）
- 阶段顶部：2017-11-13、2021-09-13、2023-05-09
- 极端底部：2015-09-15（股灾底）、2018-12-28（贸易战熊底）
- 政策底：2024-09-23（924 前夕）
- 牛市启动前：2014-07-08（数据首日）
- 震荡市：2019-07-01、2022-04-27

输出：
- 每组：output/backtests/h20269/YYYY-MM-DD起_特征/
- 汇总：H20269_扩展测试汇总.md + .html
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

if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

from rolling_position_backtest import RollingPositionBacktest
from performance_analysis import PerformanceAnalyzer


# ============================================================
# 10 个新起始日 + 特征标签
# ============================================================
CONFIGS = [
    ('2014-07-08', '牛市启动前', '#1f77b4'),   # 数据首日，乖离率 +4.93%
    ('2015-06-12', '5178牛市顶', '#d62728'),   # 极端顶部，乖离率 +73.35%
    ('2015-09-15', '股灾底2.0',  '#2ca02c'),   # 极端底部，乖离率 -6.60%
    ('2017-11-13', '蓝筹慢牛顶', '#9467bd'),   # 阶段顶，乖离率 +12.88%
    ('2018-12-28', '贸易战熊底', '#17becf'),   # 熊底，乖离率 -9.19%
    ('2019-07-01', '震荡市',     '#8c564b'),   # 震荡，乖离率 +8.98%
    ('2021-09-13', '红利阶段顶', '#e377c2'),   # 高位，乖离率 +21.96%
    ('2022-04-27', '疫情底',     '#bcbd22'),   # 疫情底，乖离率 +2.03%
    ('2023-05-09', '红利顶',     '#ff7f0e'),   # 红利顶，乖离率 +18.26%
    ('2024-09-23', '924前夕',    '#7f7f7f'),   # 政策底，乖离率 -1.48%
]

STOCK_NAME = 'H20269'


def run_single(start_date, feature, color):
    """运行单组回测，返回指标字典"""
    output_dir = f'output/backtests/h20269/{start_date}起_{feature}'

    print(f"\n{'#'*80}")
    print(f"# 起始日: {start_date}  特征: {feature}")
    print(f"# 输出目录: {output_dir}")
    print(f"{'#'*80}\n")

    bt = RollingPositionBacktest(
        csv_file_path=f'data/{STOCK_NAME}历史数据.csv',
        invest_days=40,
        sell_threshold_a=15.0,
        sell_threshold_b=17.5,
        cash_return_rate=1.2,
        initial_capital=100000,
        start_date=start_date,
        end_date=None,
        dca_tiers=None,
        # 交易成本使用默认值（启用）
    )
    bt.run(output_dir=output_dir)

    # 时间维度分析（2026-08-23 补齐）：此前本脚本从不调用 PerformanceAnalyzer，
    # 导致这 10 组只有 CSV 没有报告，与 run_multiple 的 3 组产物不一致。
    daily_csv = os.path.join(output_dir, f'{STOCK_NAME}_滚动仓位每日记录.csv')
    try:
        pa = PerformanceAnalyzer.from_backtest(daily_csv, bt)
        pa.plot_analysis(os.path.join(output_dir, '时间维度分析_综合可视化.html'))
        pa.generate_report(os.path.join(output_dir, '时间维度分析报告.md'))
    except Exception as e:
        print(f'  [WARN] 时间维度分析失败: {type(e).__name__}: {e}')

    metrics = bt.calculate_metrics()
    return {
        'start_date_str': start_date,
        'feature': feature,
        'color': color,
        'output_dir': output_dir,
        'metrics': metrics,
        'daily_csv': os.path.join(output_dir, f'{STOCK_NAME}_滚动仓位每日记录.csv'),
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
    print(f"{STOCK_NAME} 扩展测试：10 个新起始日")
    print(f"起始日列表: {[(c[0], c[1]) for c in CONFIGS]}")
    print("=" * 80)

    results = []
    for start_date, feature, color in CONFIGS:
        r = run_single(start_date, feature, color)
        results.append(r)


    print(f"\n{'='*80}")
    print(f"✅ 全部完成！")
    print(f"{'='*80}")
