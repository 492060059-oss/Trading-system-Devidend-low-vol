# -*- coding: utf-8 -*-
"""重构后修正路径引用

output/ 目录改成三层结构：
    output/backtests/h20269/<起始日>起_<特征>/
    output/backtests/etf512890/<起始日>起_<特征>/
    output/backtests/comparisons/<汇总文件>
    output/analysis/    output/reports/

本脚本把代码里的旧路径逐一替换。沿用 build_legacy.py 的纪律：
每处替换必须命中【预期次数】，否则立即退出 —— 防止"以为改了其实没改"。
"""
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

H  = 'output/backtests/h20269'
E  = 'output/backtests/etf512890'
C  = 'output/backtests/comparisons'

# (相对路径, [(旧, 新, 预期命中次数), ...])
JOBS = [
    ('scripts/run_multiple_backtests.py', [
        ("('2016-01-01', 'output/rolling_output_2016-01起_深度定投策略')",
         f"('2016-01-01', '{H}/2016-01起_深度定投策略')", 1),
        ("('2018-01-01', 'output/rolling_output_2018-01起_深度定投策略')",
         f"('2018-01-01', '{H}/2018-01起_深度定投策略')", 1),
        ("('2020-01-01', 'output/rolling_output_2020-01起_深度定投策略')",
         f"('2020-01-01', '{H}/2020-01起_深度定投策略')", 1),
        ("save_md='output/跨起始日对比汇总.md'", f"save_md='{C}/跨起始日对比汇总.md'", 1),
        ("save_html='output/跨起始日对比.html'", f"save_html='{C}/跨起始日对比.html'", 1),
    ]),
    ('scripts/run_extended_backtests.py', [
        ("f'output/rolling_output_{STOCK_NAME}_{start_date}起_{feature}'",
         f"f'{H}/{{start_date}}起_{{feature}}'", 1),
        ("save_md=f'output/{STOCK_NAME}_扩展测试汇总.md'",
         f"save_md=f'{C}/{{STOCK_NAME}}_扩展测试汇总.md'", 1),
        ("save_html=f'output/{STOCK_NAME}_扩展测试汇总.html'",
         f"save_html=f'{C}/{{STOCK_NAME}}_扩展测试汇总.html'", 1),
        ('- 每组：rolling_output_H20269_YYYY-MM-DD起_特征/',
         f'- 每组：{H}/YYYY-MM-DD起_特征/', 1),
    ]),
    ('scripts/run_512890_backtests.py', [
        ("f'output/rolling_output_{STOCK_NAME}_{start_date}起_{feature}'",
         f"f'{E}/{{start_date}}起_{{feature}}'", 1),
        ("save_md=f'output/{STOCK_NAME}_ETF跟踪能力测试汇总.md'",
         f"save_md=f'{C}/{{STOCK_NAME}}_ETF跟踪能力测试汇总.md'", 1),
        ("save_html=f'output/{STOCK_NAME}_ETF跟踪能力测试汇总.html'",
         f"save_html=f'{C}/{{STOCK_NAME}}_ETF跟踪能力测试汇总.html'", 1),
    ]),
    ('scripts/regenerate_charts.py', [
        ('- 路径：output/rolling_output_*/', f'- 路径：{H}/*/ 与 {E}/*/', 1),
        # 单组图：两层目录都要扫
        ("output_dirs = sorted(glob.glob('output/rolling_output_*/'))",
         f"output_dirs = (sorted(glob.glob('{H}/*/'))\n"
         f"                   + sorted(glob.glob('{E}/*/')))", 1),
        ("('2016-01-01', 'output/rolling_output_2016-01起_深度定投策略', '#1f77b4')",
         f"('2016-01-01', '{H}/2016-01起_深度定投策略', '#1f77b4')", 1),
        ("('2018-01-01', 'output/rolling_output_2018-01起_深度定投策略', '#ff7f0e')",
         f"('2018-01-01', '{H}/2018-01起_深度定投策略', '#ff7f0e')", 1),
        ("('2020-01-01', 'output/rolling_output_2020-01起_深度定投策略', '#2ca02c')",
         f"('2020-01-01', '{H}/2020-01起_深度定投策略', '#2ca02c')", 1),
        ("dir_name = f'output/rolling_output_H20269_{start}起_{feature}'",
         f"dir_name = f'{H}/{{start}}起_{{feature}}'", 1),
        ("dir_name = f'output/rolling_output_512890_{start}起_{feature}'",
         f"dir_name = f'{E}/{{start}}起_{{feature}}'", 1),
        ("save_html='output/跨起始日对比.html'", f"save_html='{C}/跨起始日对比.html'", 1),
        ("save_html='output/H20269_扩展测试汇总.html'",
         f"save_html='{C}/H20269_扩展测试汇总.html'", 1),
        ("save_html='output/512890_ETF跟踪能力测试汇总.html'",
         f"save_html='{C}/512890_ETF跟踪能力测试汇总.html'", 1),
    ]),
    ('core/analyze_ma250.py', [
        ("output_dir='output/analysis_output'", "output_dir='output/analysis'", 1),
    ]),
    ('core/performance_analysis.py', [
        ("default='output/rolling_output_2015-05起_深度定投策略/H20269_滚动仓位每日记录.csv'",
         f"default='{H}/2015-05起_深度定投策略/H20269_滚动仓位每日记录.csv'", 1),
    ]),
    ('core/rolling_position_backtest.py', [
        # 默认输出目录：仅作兜底，改到 backtests 下避免污染 output/ 根
        ("def save_results(self, output_dir='output/rolling_output'):",
         f"def save_results(self, output_dir='{H}/_default'):", 1),
        ("def run(self, output_dir='output/rolling_output'):",
         f"def run(self, output_dir='{H}/_default'):", 1),
    ]),
    ('tools/audit_checks.py', [
        ("f = 'output/rolling_output_2015-05起_深度定投策略/H20269_滚动仓位每日记录.csv'",
         f"f = '{H}/2015-05起_深度定投策略/H20269_滚动仓位每日记录.csv'", 2),
        ("dirs = sorted(glob.glob('output/rolling_output_*/'))",
         f"dirs = (sorted(glob.glob('{H}/*/')) + sorted(glob.glob('{E}/*/')))", 1),
    ]),
    ('tools/ab_compare/build_legacy.py', [
        ("DST  = os.path.join(ROOT, 'output', '_ab_compare', _A.dst)",
         "DST  = os.path.join(ROOT, 'tools', 'ab_compare', _A.dst)", 1),
        # 源码已搬进 core/
        ("shutil.copy2(os.path.join(ROOT, fn), os.path.join(DST, fn))",
         "shutil.copy2(os.path.join(ROOT, 'core', fn), os.path.join(DST, fn))", 1),
    ]),
    ('tools/ab_compare/run_ab.py', [
        ("sys.path.insert(0, os.path.join(ROOT, 'output', '_ab_compare', os.environ.get('AB_SRC', 'legacy')))",
         "sys.path.insert(0, os.path.join(ROOT, 'tools', 'ab_compare', os.environ.get('AB_SRC', 'legacy')))", 1),
        ("sys.path.insert(0, ROOT)",
         "sys.path.insert(0, os.path.join(ROOT, 'core'))", 1),
        ("tmp = f'output/_ab_compare/_tmp_{args.version}_{label}.csv'",
         "tmp = f'tools/ab_compare/_tmp_{args.version}_{label}.csv'", 1),
    ]),
    ('tools/ab_compare/make_report.py', [
        ("D = 'output/_ab_compare'", "D = 'tools/ab_compare'", 1),
        ('output/_ab_compare/build_legacy.py', 'tools/ab_compare/build_legacy.py', 3),
        ('output/_ab_compare/run_ab.py', 'tools/ab_compare/run_ab.py', 4),
        ('output/_ab_compare/result_legacy.json', 'tools/ab_compare/result_legacy.json', 1),
        ('output/_ab_compare/result_current.json', 'tools/ab_compare/result_current.json', 1),
        ('output/_ab_compare/result_only_$B.json', 'tools/ab_compare/result_only_$B.json', 1),
        ('output/_ab_compare/result_only_BD.json', 'tools/ab_compare/result_only_BD.json', 1),
        ('output/_ab_compare/make_report.py', 'tools/ab_compare/make_report.py', 1),
        ('`output/rolling_output_*/` 下 16 组', f'`{H}/`、`{E}/` 下 16 组', 1),
    ]),
    ('tools/ab_compare/mark_stale.py', [
        ("`output/_ab_compare/改前改后对比报告.md`",
         "`tools/ab_compare/改前改后对比报告.md`", 1),
        ("+ sorted(glob.glob('output/rolling_output_*/时间维度分析报告.md')))",
         f"+ sorted(glob.glob('{H}/*/时间维度分析报告.md'))\n"
         f"           + sorted(glob.glob('{E}/*/时间维度分析报告.md')))", 1),
    ]),
]

fail = 0
for rel, pairs in JOBS:
    p = os.path.join(ROOT, rel)
    if not os.path.exists(p):
        print(f'  [MISS] {rel}')
        fail += 1
        continue
    s = open(p, encoding='utf-8').read()
    orig = s
    for old, new, want in pairs:
        n = s.count(old)
        if n != want:
            # 已经改过？
            if n == 0 and s.count(new) >= want:
                print(f'  [SKIP] {rel}: 「{old[:50]}」已是新路径')
                continue
            print(f'  [FATAL] {rel}: 「{old[:60]}」命中 {n} 次（应为 {want}）')
            fail += 1
            continue
        s = s.replace(old, new)
    if s != orig:
        open(p, 'w', encoding='utf-8').write(s)
        print(f'  [OK  ] {rel}')
    else:
        print(f'  [NOOP] {rel}')

if fail:
    print(f'\n❌ {fail} 处未按预期命中，请人工检查后再继续')
    sys.exit(1)
print('\n✅ 全部路径替换按预期命中')
