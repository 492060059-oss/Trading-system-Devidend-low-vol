# -*- coding: utf-8 -*-
"""从已有回测目录重新生成所有图与报告

- 路径：output/backtests/h20269/*/ 与 output/backtests/etf512890/*/
- 产物：时间维度分析_综合可视化.html + 时间维度分析报告.md（每组仅此两份）

用途：绘图/报告函数升级后，批量刷新已生成的产物，不必重跑全部 run_*.py。

2026-08-23 变更
--------------
① 删除 regenerate_single_chart()。它生成的 {stock}_滚动仓位收益率对比.html
   与 时间维度分析_综合可视化.html 高度重复（收益率对比 / 价格vsMA250 /
   持仓比例三个子图完全同源），后者更全；「价格 vs MA250」已合并进后者
   子图①的次坐标轴。该 html 不再生成。
② 报告改为【在内存里重跑一遍回测】取 metrics + 策略参数后再生成。
   原因：新版报告含三方对照表（策略/满仓/静态混合）与成本统计，这些数
   来自 calculate_metrics() 与回测器实例，每日记录 CSV 里没有。
   重跑不落盘，不会覆盖既有 CSV。
   组参数从 build_cross_group_report.GROUPS 取，保证与各 run_*.py 一致 ——
   避免此处另抄一份参数、日后两边漂移。
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


import os
import sys
import glob

if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

from rolling_position_backtest import RollingPositionBacktest
from performance_analysis import PerformanceAnalyzer
from build_cross_group_report import GROUPS


# 目录 -> (标的, 起始日, 初始资金)，唯一事实来源是 build_cross_group_report.GROUPS
GROUP_PARAMS = {
    os.path.normpath(d): (symbol, start, cap)
    for d, symbol, start, cap, _feat, _src in GROUPS
}


def regenerate_time_analysis(output_dir, stock_name):
    """重新生成 时间维度分析_综合可视化.html + 时间维度分析报告.md"""
    daily_csv = os.path.join(output_dir, f'{stock_name}_滚动仓位每日记录.csv')
    if not os.path.exists(daily_csv):
        return False, 'no-csv'

    key = os.path.normpath(output_dir)
    params = GROUP_PARAMS.get(key)

    bt = None
    if params:
        symbol, start_date, capital = params
        # 内存中重跑，只为取 metrics 与策略参数；不调用 save_results，不落盘
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

    if bt is not None:
        analyzer = PerformanceAnalyzer.from_backtest(daily_csv, bt)
        mode = 'full'
    else:
        # 未登记在 GROUPS 里的目录：退化为纯 CSV 模式，报告会显式标注
        # 「缺少静态混合基准/参数/成本」，而不是静默省略。
        analyzer = PerformanceAnalyzer(daily_csv)
        mode = 'csv-only'

    analyzer.plot_analysis(os.path.join(output_dir, '时间维度分析_综合可视化.html'))
    analyzer.generate_report(os.path.join(output_dir, '时间维度分析报告.md'))
    return True, mode


# ============================================================
# 主流程
# ============================================================
def main():
    print("=" * 80)
    print("批量重新生成时间维度分析（3 子图新布局 + 三方对照表）")
    print("=" * 80)

    output_dirs = (sorted(glob.glob('output/backtests/h20269/*/'))
                   + sorted(glob.glob('output/backtests/etf512890/*/')))
    print(f"找到 {len(output_dirs)} 个回测输出目录\n")

    n_full = n_csv = n_skip = 0
    for d in output_dirs:
        files_in_dir = glob.glob(os.path.join(d, '*_滚动仓位每日记录.csv'))
        if not files_in_dir:
            n_skip += 1
            continue
        csv_name = os.path.basename(files_in_dir[0])
        stock_name = csv_name.replace('_滚动仓位每日记录.csv', '')

        try:
            ok, mode = regenerate_time_analysis(d, stock_name)
        except Exception as e:
            n_skip += 1
            print(f"  ❌ {d.strip('/')}/  {type(e).__name__}: {e}")
            continue

        if not ok:
            n_skip += 1
            continue
        if mode == 'full':
            n_full += 1
            print(f"  ✅ {d.strip('/')}/（完整：含三方对照表与成本）")
        else:
            n_csv += 1
            print(f"  ⚠️  {d.strip('/')}/（仅CSV模式：该目录未登记在 GROUPS，"
                  f"报告缺静态混合/参数/成本）")

    # === 跨起始日对比图已移除（2026-08 决定）===
    # 原先在此生成 comparisons/ 下 3 张 html（跨起始日对比 / H20269_扩展测试汇总
    # / 512890_ETF跟踪能力测试汇总）。移除原因：
    #   ① 子图②「不同起点的基准累计收益率」是同一条价格序列的多次重新归一化，
    #      实测三组重叠区间收盘价逐日绝对差 = 0.0000000000，不含任何新信息；
    #   ② 子图①的横向比较已被 output/backtests/横向统计报告.md 完整覆盖，且后者
    #      多出年化/夏普/索提诺/同仓位混合超额与分阶段胜负明细；
    #   ③ 曲线对比改为 21 组【超额】曲线：横向统计_超额曲线对比.html。
    # 替代命令： python scripts/backtest/build_cross_group_report.py
    print("\n--- 跨起始日对比图已移除，改由 build_cross_group_report.py 生成 ---")
    print("    -> 横向统计报告.md / 横向统计_超额曲线对比.html")

    print("\n" + "=" * 80)
    print(f"✅ 完成：{n_full} 组完整 / {n_csv} 组仅CSV / {n_skip} 组跳过")
    print("=" * 80)


if __name__ == '__main__':
    main()
