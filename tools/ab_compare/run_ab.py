# -*- coding: utf-8 -*-
"""A/B 对比运行器：同一批回测，分别用【改前】和【改后】源码各跑一遍

关键设计（为了经得起检查）：
1. 两个版本跑的是【同一份 CSV、同一组参数】，唯一变量是源码；
2. 每个版本在独立子进程里跑，sys.path 决定加载哪份源码，
   杜绝同一进程里模块缓存互相污染；
3. 结果落成 JSON，再由 make_report.py 生成对比表 —— 数据与排版分离，
   任何人都可以只看 JSON 自行核对。
"""
import sys, os, io, json, contextlib, argparse

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

ap = argparse.ArgumentParser()
ap.add_argument('--version', required=True, choices=['legacy', 'current'])
ap.add_argument('--out', required=True)
args = ap.parse_args()

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
os.chdir(ROOT)   # CSV 用相对路径读，工作目录必须是项目根

if args.version == 'legacy':
    sys.path.insert(0, os.path.join(ROOT, 'tools', 'ab_compare', os.environ.get('AB_SRC', 'legacy')))
else:
    sys.path.insert(0, os.path.join(ROOT, 'core'))

from rolling_position_backtest import RollingPositionBacktest
from performance_analysis import PerformanceAnalyzer
import performance_analysis as _pa

# ---- 被测组：14 个 H20269 起始日 + 2 个 ETF（Bug D 免征只在 ETF 体现）----
GROUPS = [
    ('H20269', '2015-05-01'), ('H20269', '2016-01-01'),
    ('H20269', '2018-01-01'), ('H20269', '2020-01-01'),
    ('H20269', '2014-07-08'), ('H20269', '2015-06-12'),
    ('H20269', '2015-09-15'), ('H20269', '2017-11-13'),
    ('H20269', '2018-12-28'), ('H20269', '2019-07-01'),
    ('H20269', '2021-09-13'), ('H20269', '2022-04-27'),
    ('H20269', '2023-05-09'), ('H20269', '2024-09-23'),
    ('512890', '2020-02-03'), ('512890', '2023-05-09'),
]

# 需要记录的指标（改后新增的键在 legacy 里不存在 -> 记 None）
KEYS = [
    '回测天数', '回测年数',
    '策略累计收益率', '策略年化收益率', '策略最大回撤',
    '策略年化波动率', '策略夏普比率', '策略索提诺比率', '策略卡尔马比率',
    '基准累计收益率', '基准年化收益率', '基准最大回撤',
    '基准年化波动率', '基准夏普比率', '基准索提诺比率', '基准卡尔马比率',
    '超额收益(累计)', '超额收益(年化)', '夏普差',
    '总佣金', '总印花税', '总交易成本',
    '平均仓位比例',
    # 改后新增：同仓位混合基准 + 成本披露
    '混合基准权重%', '混合基准累计收益率', '混合基准年化收益率',
    '混合基准最大回撤', '混合基准夏普比率', '混合基准索提诺比率',
    '择时超额(累计)', '择时回撤差(策略-混合)',
    '实际佣金率%', '触发最低佣金笔数', '印花税免征',
]

out = {'version': args.version, 'groups': {}}

for sym, start in GROUPS:
    label = f'{sym}_{start}'
    csv = f'data/{sym}历史数据.csv'
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            bt = RollingPositionBacktest(
                csv_file_path=csv, invest_days=40,
                sell_threshold_a=15.0, sell_threshold_b=17.5,
                cash_return_rate=1.2, initial_capital=100000,
                start_date=start, end_date=None, dca_tiers=None)
            bt.load_data()
            bt.run_backtest()
            m = bt.calculate_metrics()
        rec = {}
        for k in KEYS:
            v = m.get(k, None)
            if hasattr(v, 'item'):
                v = v.item()
            if isinstance(v, bool):
                v = bool(v)
            elif v is not None and not isinstance(v, (int, float, str)):
                v = str(v)
            rec[k] = v
        rec['起始日期'] = str(m['起始日期'])[:10]
        rec['结束日期'] = str(m['结束日期'])[:10]
        rec['_error'] = None
    except Exception as e:
        rec = {'_error': f'{type(e).__name__}: {e}'}

    # ---- 阶段归因（Bug E / F 的直接观测面）----
    try:
        with contextlib.redirect_stdout(buf):
            tmp = f'tools/ab_compare/_tmp_{args.version}_{label}.csv'
            bt.daily_df.to_csv(tmp, index=False, encoding='utf-8-sig')
            pa = PerformanceAnalyzer(tmp)
            ph = pa.analyze_phases()
        rec['阶段数'] = int(len(ph))
        rec['阶段_跑赢数'] = int((ph['超额阶段收益%'] > 0).sum())
        rec['阶段_交易日合计'] = int(ph['交易日数'].sum())
        rec['阶段_全程交易日'] = int(len(pa.df))
        rec['阶段_覆盖缺口'] = rec['阶段_全程交易日'] - rec['阶段_交易日合计']
        # 连乘还原：各段策略收益连乘 vs 全程总收益
        chain = 1.0
        for v in ph['策略阶段收益%']:
            chain *= (1 + v / 100)
        rec['阶段_连乘还原%'] = (chain - 1) * 100
        tot = (pa.df['总资产'].iloc[-1] / pa.df['总资产'].iloc[0] - 1) * 100
        rec['阶段_全程总收益%'] = float(tot)
        rec['阶段_连乘偏差pp'] = rec['阶段_连乘还原%'] - rec['阶段_全程总收益%']
        rec['阶段_异常'] = None
        os.remove(tmp)
    except Exception as e:
        rec['阶段_异常'] = f'{type(e).__name__}: {e}'

    out['groups'][label] = rec
    err = rec.get('_error') or rec.get('阶段_异常') or ''
    print(f"  [{args.version}] {label:24s} "
          f"累计={rec.get('策略累计收益率', float('nan')):>8.2f} "
          f"夏普={rec.get('策略夏普比率', float('nan')):>6.3f}  {err}")

with open(args.out, 'w', encoding='utf-8') as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
print(f'\n-> {args.out}')
