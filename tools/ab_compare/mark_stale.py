# -*- coding: utf-8 -*-
"""给修复前生成的旧产出加「数据过期」横幅

修复 A/B/D/E/F/G/H 后，output/ 下所有报告的数值都已失效，但文件本身还在。
不重新生成（等 J、C 修完统一重跑），但必须让任何打开它的人立刻知道数据是旧的 ——
否则这些文件会被当成当前结论引用。

幂等：已加过横幅的文件会跳过。
"""
import sys, os, glob
sys.stdout.reconfigure(encoding='utf-8')
os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

MARK = '<!-- STALE-DATA-BANNER -->'

BANNER = f'''{MARK}
> # ⚠️ 本文件数据已过期，请勿引用
>
> **本文件生成于 2026-08-23 的 bug 修复之前，其中所有数值均已失效。**
>
> 已修复并影响本文件全部数字的 7 个 bug：
> **A** 无风险利率单位错配、**B** 现金利息漏计日历日、**D** 印花税规则（买入错征 + ETF 未免征）、
> **E** 阶段收益率公式、**F** 阶段划分静默漏天（353 个组×交易日）、
> **G** 索提诺分母口径、**H** 年化交易日数硬编码。
>
> 修复后的实际影响（16 组回测实测）：
> 累计收益率 **16/16 组上升**（+0.38 ~ +5.92 pp）、夏普 **16/16 组下降**、索提诺 **16/16 组上升**、
> 阶段胜负 **25/28 → 21/28**。
>
> 📄 **请改看**：`tools/ab_compare/改前改后对比报告.md`（含逐 bug 归因与可复现脚本）
> 📄 **进度与结论**：`progress.md` 第 0.21 章节
>
> 🔴 **另一项必须知道的结论**：新增同仓位静态混合基准后确认，策略最大回撤
> **12/16 组劣于同仓位混合基准**。本文件中一切「控回撤能力」「回撤砍半」类表述**均不成立** ——
> 低回撤是低仓位的机械结果，不是择时能力。
>
> ⏳ 本文件将在 Bug J、C 修复后统一重新生成。

---

'''

targets = (['output/跨起始日对比汇总.md',
            'output/H20269_扩展测试汇总.md',
            'output/512890_ETF跟踪能力测试汇总.md']
           + sorted(glob.glob('output/backtests/h20269/*/时间维度分析报告.md'))
           + sorted(glob.glob('output/backtests/etf512890/*/时间维度分析报告.md')))

added = skipped = missing = 0
for p in targets:
    if not os.path.exists(p):
        print(f'  [MISS] {p}')
        missing += 1
        continue
    s = open(p, encoding='utf-8').read()
    if MARK in s:
        print(f'  [SKIP] {p}  (已有横幅)')
        skipped += 1
        continue
    open(p, 'w', encoding='utf-8').write(BANNER + s)
    print(f'  [ADD ] {p}')
    added += 1

print(f'\n加横幅 {added} 个，跳过 {skipped} 个，缺失 {missing} 个')
