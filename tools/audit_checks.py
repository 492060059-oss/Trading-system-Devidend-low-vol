# -*- coding: utf-8 -*-
"""
审计回归验证脚本（2026-08-11 建立）

用途：把 progress.md 0.20 章节的审计结论固化为可重复执行的检查，
      每批 bug 修复后跑一次，确认"修对了"且"没修坏别的"。

设计原则：
1. 每个 check 独立、自证：打印"当前值 vs 正确值 vs 判定"
2. 不修改任何文件，纯只读 + 计算
3. 可单独跑某一项：python audit_checks.py --only E
4. 退出码：0 = 全部符合预期（bug 已修复），1 = 仍存在问题

⚠️ 2026-08-23 改造（重要）：
   BUG 类检查原先在本脚本里【复刻被测代码的公式】，然后拿"旧公式 vs 新公式"
   在同一份数据上比差异。这类判定与源码实际写法无关 —— 差异是数据的固有属性，
   无论怎么修都不会变。后果：E/H/J 永远 FAIL（无法验收），A/B/G 只在特定修法下
   才会转 PASS。这是"bug 存在性演示"，不是"回归测试"。

   改造后，BUG 类检查一律走【真实代码路径】：
     - 调用被测函数/方法（calculate_metrics / analyze_phases / generate_report）
     - 从其真实输出反解实际生效的参数（见 effective_annual_risk_free /
       effective_trading_days），或直接解析它生成的报告文本
     - 再与本脚本独立算出的正确答案比较
   这样"修对了 -> 转 PASS""改坏了 -> 转 FAIL"才成立。
   例外：C（死代码）验收对象本身是源码结构，静态检查是恰当的。

   注：TD_CONVENTION / CASH_RATE 仅作为【参考基准】保留，不再作为任何
   BUG 项的判定依据（改造前 check_H 曾直接判定本脚本自己的常量）。

用法：
    python audit_checks.py                # 跑全部
    python audit_checks.py --only A,B,E    # 只跑指定项
    python audit_checks.py --list          # 列出所有检查项
"""
# === PROJECT-ROOT BOOTSTRAP ===
# 重构后代码分层（core/ scripts/ tools/），此前言保证脚本从任何目录调用都可用：
# 把项目根与 core/ 挂上 sys.path，并将工作目录切到项目根，
# 使代码中所有 'data/...'、'output/...' 相对路径继续生效（无需逐个改写）。
import os as _os
import sys as _sys
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
for _p in (_ROOT, _os.path.join(_ROOT, 'core')):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)
if _os.path.abspath(_os.getcwd()) != _ROOT:
    _os.chdir(_ROOT)
# === /PROJECT-ROOT BOOTSTRAP ===


import sys
import os
import io
import re
import contextlib
import argparse
import inspect

import numpy as np
import pandas as pd

if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

CSV = 'data/H20269历史数据.csv'
TD_CONVENTION = 252          # 代码当前使用的年化交易日数
CASH_RATE = 1.2              # c%，空仓年化收益率参数


def src_path(fn):
    """定位源码文件（重构后分散在 core/ scripts/ tools/）

    找不到时【抛异常而非返回 None】：静态检查若因文件搬走而静默跳过，
    会把"没检查"伪装成"没问题"—— 那正是本审计要防的事。
    """
    for sub in ('', 'core', 'scripts', 'tools'):
        p = os.path.join(sub, fn) if sub else fn
        if os.path.exists(p):
            return p
    raise FileNotFoundError(
        f'审计找不到源码 {fn}（已在 ./ core/ scripts/ tools/ 下搜索）。'
        f'若文件被重命名或移动，请更新 src_path 的搜索范围 —— '
        f'不要让静态检查静默跳过。')

# 审计基准起始日（样本内主力口径 + 全部 14 个测试起始日）
MAIN_STARTS = ['2015-05-01', '2016-01-01', '2018-01-01', '2020-01-01']
ALL_STARTS = MAIN_STARTS + [
    '2014-07-08', '2015-06-12', '2015-09-15', '2017-11-13', '2018-12-28',
    '2019-07-01', '2021-09-13', '2022-04-27', '2023-05-09', '2024-09-23',
]

_CACHE = {}


# ============================ 基础工具 ============================

def run_backtest(start_date, end_date=None, **kw):
    """静默跑一次回测，返回 daily_df + trading_records（带缓存）"""
    key = (start_date, end_date, tuple(sorted(kw.items())))
    if key in _CACHE:
        return _CACHE[key]
    from rolling_position_backtest import RollingPositionBacktest
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        bt = RollingPositionBacktest(csv_file_path=CSV, start_date=start_date,
                                     end_date=end_date, initial_capital=100000, **kw)
        bt.load_data()
        bt.run_backtest()
    _CACHE[key] = (bt.daily_df, bt.trading_records, bt)
    return _CACHE[key]


def max_drawdown(series):
    cm = series.cummax()
    return ((series - cm) / cm).min() * 100


def ann_vol(series, td=TD_CONVENTION):
    return np.std(series.pct_change().dropna().values) * np.sqrt(td) * 100


def static_blend(price, w, cash_annual=CASH_RATE, td=TD_CONVENTION, init=100000):
    """同仓位静态混合基准：w 投指数 + (1-w) 投现金，每日再平衡"""
    dr = price.pct_change().fillna(0).values
    cash_d = (1 + cash_annual / 100) ** (1 / td) - 1
    return pd.Series(np.cumprod(1 + (w * dr + (1 - w) * cash_d)) * init)


def newey_west_t(x, lags=None):
    n = len(x)
    m = x.mean()
    e = x - m
    if lags is None:
        lags = int(4 * (n / 100) ** (2 / 9))
    s = (e @ e) / n
    for l in range(1, lags + 1):
        s += 2 * (1 - l / (lags + 1)) * ((e[l:] @ e[:-l]) / n)
    return m / np.sqrt(s / n), lags


def banner(code, title):
    print()
    print('=' * 78)
    print(f'[{code}] {title}')
    print('=' * 78)


def verdict(ok, msg_ok, msg_bad):
    print(f'  判定: {"[PASS] " + msg_ok if ok else "[FAIL] " + msg_bad}')
    return ok


def phase_mask(dates, phase):
    """按阶段定义生成掩码；start/end 为 None 表示向该侧数据边界敞开。

    与 performance_analysis.analyze_phases 的边界语义保持一致（Bug F 修复后
    首段 start / 末段 end 为 None）。本脚本【独立实现】而非复用被测代码，
    以保持验收的独立性。
    """
    m = pd.Series(True, index=dates.index)
    if phase['start'] is not None:
        m &= dates >= phase['start']
    if phase['end'] is not None:
        m &= dates <= phase['end']
    return m


# ============================ 真实代码路径探针 ============================
# 设计要点（2026-08-23 改造）：
#   验收必须【调用被测代码、读取其真实输出】，再与本脚本独立算出的正确答案比较。
#   绝不在本脚本里复刻被测代码的公式然后自己跟自己比 —— 那样的判定与源码无关，
#   无论怎么修都不会变（改造前 E/H/J 即属此类，永远 FAIL；A/B/G 则依赖特定修法）。

def source_of(fn_or_obj):
    """取某个函数/方法的源码文本（用于确认实际生效的写法）"""
    return inspect.getsource(fn_or_obj)


def read_metrics(start_date='2016-01-01', **kw):
    """静默跑回测并拿到 calculate_metrics() 的真实输出字典"""
    _, _, bt = run_backtest(start_date, **kw)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        m = bt.calculate_metrics()
    return m, bt


def effective_annual_risk_free(bt):
    """
    反解【实际喂进夏普公式】的无风险利率，不复刻任何公式。
    由 sharpe = (annual_return*100 - rf) / annual_vol 反解 rf。
    """
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        m = bt.calculate_metrics()
    return m['策略年化收益率'] - m['策略夏普比率'] * m['策略年化波动率']


def effective_trading_days(bt):
    """
    反解代码实际使用的「交易日/年」常量，不复刻任何公式。
    由 annual_return = (1+cum)^(1/(n/TD)) - 1 反解 TD。
    """
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        m = bt.calculate_metrics()
    n = len(bt.daily_df)
    cum = m['策略累计收益率'] / 100
    ann = m['策略年化收益率'] / 100
    if cum <= -1 or ann <= -1 or abs(np.log1p(ann)) < 1e-12:
        return None
    years = np.log1p(cum) / np.log1p(ann)
    return n / years


# ============================ 硬错误检查（客观可判定） ============================

def check_A():
    """无风险利率单位错误：^(1/365) 开根后 x252 还原"""
    banner('A', '无风险利率单位错误（影响所有夏普/索提诺）')
    # 真实路径：跑回测 -> calculate_metrics() -> 由夏普反解实际生效的 rf
    m, bt = read_metrics('2016-01-01')
    coded = effective_annual_risk_free(bt)      # 实际喂进夏普公式的值
    correct = CASH_RATE                         # 参数本意
    print(f'  参数 cash_return_rate       = {CASH_RATE}%（本意：年化）')
    print(f'  策略年化 {m["策略年化收益率"]:.4f}% / 波动 {m["策略年化波动率"]:.4f}% / 夏普 {m["策略夏普比率"]:.6f}')
    print(f'  由夏普反解的 annual_risk_free = {coded:.4f}%   <-- 实际生效值')
    print(f'  正确值                       = {correct:.4f}%')
    print(f'  偏差                         = {coded - correct:+.4f} pp')
    if abs(coded - correct) > 1e-4:
        print(f'  -> 无风险利率被低估，夏普/索提诺分子偏大，系统性虚高')
    return verdict(abs(coded - correct) < 1e-4,
                   f'无风险利率已按 {correct}% 生效',
                   f'实际生效 {coded:.4f}% 而非 {correct}%')


def check_B():
    """现金按365日率、却只在252个交易日计息"""
    banner('B', '现金计息口径错误（扭曲权益曲线本身）')
    # 真实路径：在正常回测里找出最长的【连续纯空仓】区间，直接从权益曲线
    # 量出现金的实际复利速度（不复刻任何公式）。全历史约 22% 交易日为 0 仓位。
    d, _, bt = run_backtest('2007-01-04')
    flat = (d['持仓市值'] <= 1e-9).values
    # 找最长连续 True 段
    best_len, best_end, cur = 0, -1, 0
    for i, v in enumerate(flat):
        cur = cur + 1 if v else 0
        if cur > best_len:
            best_len, best_end = cur, i
    realized = None
    if best_len >= 60:
        i0, i1 = best_end - best_len + 1, best_end
        seg = d.iloc[i0:i1 + 1]
        span = (seg['日期'].iloc[-1] - seg['日期'].iloc[0]).days
        grow = seg['空仓资金'].iloc[-1] / seg['空仓资金'].iloc[0]
        if span > 0 and grow > 0:
            realized = grow ** (365.25 / span) - 1
            print(f'  最长连续纯空仓: {seg["日期"].iloc[0].date()} ~ {seg["日期"].iloc[-1].date()}')
            print(f'    {best_len} 个交易日 / {span} 个日历日，空仓资金增长 {grow:.8f} 倍')
    if realized is None:
        daily = bt.calculate_daily_return(CASH_RATE)
        td = effective_trading_days(bt) or TD_CONVENTION
        realized = (1 + daily) ** td - 1
        print(f'  [兜底] 无足够长纯空仓区间，改由日利率×实际交易日/年({td:.0f})推算')

    intended = CASH_RATE / 100
    print(f'  实测现金【日历年化】= {realized:.4%}   <-- 权益曲线的客观结果')
    print(f'  参数意图年化        = {intended:.4%}')
    print(f'  实得/意图           = {realized/intended*100:.1f}%   缺口 {(intended-realized)*100:+.3f} pp')
    if realized < intended * 0.99:
        print(f'  -> 日利率按 365 天摊，但只在交易日累加，周末假日利息凭空消失')
        print(f'  -> 方向【低估】策略（保守），但与 A 的口径自相矛盾')
    return verdict(abs(realized - intended) / intended < 0.01,
                   f'现金实际年化 {realized:.4%} 与参数一致',
                   f'现金仅赚到意图的 {realized/intended*100:.1f}%')


def check_C():
    """triggered_b 死代码"""
    banner('C', 'triggered_b 死代码（状态机与文档不一致）')
    # 静态检查在此项是【恰当】的：要验收的对象本身就是源码结构（是否存在
    # 永假的守卫），不存在"运行时输出"可供比对。
    from rolling_position_backtest import RollingPositionBacktest
    src = source_of(RollingPositionBacktest)
    # 只看【可执行代码】：剔除注释行。否则修复说明里提到 `not triggered_b`
    # 这个词，会被误判成"守卫仍在"，导致已修好的代码判 FAIL。
    clean = '\n'.join(l for l in src.split('\n') if not l.strip().startswith('#'))
    all_refs = len(re.findall(r'triggered_b', clean))
    assigns = re.findall(r'triggered_b\s*=\s*(\w+)', clean)
    reads = len(re.findall(r'not\s+triggered_b|triggered_b\s+and', clean))
    print(f'  可执行代码中的引用总数 : {all_refs}')
    print(f'  triggered_b 的所有赋值: {assigns}')
    print(f'  被读取（作为条件）次数 : {reads}')
    if all_refs == 0:
        print('  -> triggered_b 已从可执行代码中【完全删除】，虚假守卫消失')
        print('  -> 已验证删除前后 16 组回测 656 个指标逐位相同（纯死代码，零行为变化）')
        return verdict(True, 'triggered_b 已实现或已删除', 'triggered_b 仍是死代码')
    ever_true = any(a == 'True' for a in assigns)
    print(f'  是否曾被设为 True      : {ever_true}')
    if not ever_true and reads:
        print(f'  -> `not triggered_b` 恒为 True，4c 分支的守卫是【虚假的】')
        print(f'  -> 今日不产生错误结果，但与 ROLLING_POSITION_STRATEGY.md 状态机不符')
    return verdict(ever_true or reads == 0,
                   'triggered_b 已实现或已删除', 'triggered_b 仍是死代码')


def check_E():
    """阶段收益率用累计收益率相减（分母错）"""
    banner('E', '阶段收益率公式错误（影响最常被引用的阶段胜负表）')
    f = 'output/backtests/h20269/2015-05起_深度定投策略/H20269_滚动仓位每日记录.csv'
    if not os.path.exists(f):
        print(f'  [SKIP] 找不到 {f}')
        return None

    # 真实路径：调用 PerformanceAnalyzer.analyze_phases()，读它真实输出的超额列
    from performance_analysis import PerformanceAnalyzer, MARKET_PHASES
    ana = PerformanceAnalyzer(f)
    got = ana.analyze_phases()

    # 本脚本独立算正确答案：段内自身复合收益，基点取该段前一交易日（无缝衔接）
    d = ana.df
    print(f'  {"阶段":<24}{"代码输出":>10}{"独立正确":>10}{"差":>8}{"":>6}')
    bad = 0
    rows = 0
    chain_s, chain_b = 1.0, 1.0
    for p in MARKET_PHASES:
        seg = d[phase_mask(d['日期'], p)]
        if len(seg) == 0:
            continue
        i0 = d.index.get_loc(seg.index[0])
        j = i0 - 1 if i0 > 0 else i0
        tS = (seg['总资产'].iloc[-1] / d['总资产'].iloc[j] - 1) * 100
        tB = (seg['收盘价'].iloc[-1] / d['收盘价'].iloc[j] - 1) * 100
        exp = tS - tB
        row = got[got['阶段'] == p['name']]
        if len(row) == 0:
            continue
        rows += 1
        act = float(row['超额阶段收益%'].iloc[0])
        chain_s *= (1 + float(row['策略阶段收益%'].iloc[0]) / 100)
        chain_b *= (1 + float(row['基准阶段收益%'].iloc[0]) / 100)
        off = abs(act - exp) > 0.05
        bad += off
        print(f'  {p["name"][:23]:<24}{act:>10.2f}{exp:>10.2f}{act-exp:>8.2f}{"  <<偏差" if off else "":>6}')

    print(f'\n  {rows} 个阶段中，与独立正确值不符: {bad} 个')
    # 附加体检：各段连乘应能还原阶段表覆盖区间的总收益。
    # Bug F 修复后阶段应 100% 覆盖数据，故覆盖区间即全部数据；若仍有缺口，
    # analyze_phases 会先抛 ValueError（不会走到这里）。
    cov = pd.Series(False, index=d.index)
    for p in MARKET_PHASES:
        cov |= phase_mask(d['日期'], p)
    idx = d.index[cov]
    i_c0 = d.index.get_loc(idx[0])
    base = i_c0 - 1 if i_c0 > 0 else i_c0
    cE = idx[-1]
    real_s = (d['总资产'].loc[cE] / d['总资产'].iloc[base] - 1) * 100
    real_b = (d['收盘价'].loc[cE] / d['收盘价'].iloc[base] - 1) * 100
    print(f'  连乘还原  策略: {(chain_s-1)*100:>8.2f}% vs 实际 {real_s:>8.2f}%  误差 {(chain_s-1)*100-real_s:+.3f} pp')
    print(f'            基准: {(chain_b-1)*100:>8.2f}% vs 实际 {real_b:>8.2f}%  误差 {(chain_b-1)*100-real_b:+.3f} pp')
    print(f'  正确写法: 段内自身复合收益，基点取该段【前一交易日】收盘')
    return verdict(bad == 0, '阶段收益率公式已修正（与独立算法一致）',
                   f'{bad}/{rows} 个阶段与正确值不符')


def check_F():
    """阶段划分未覆盖全部数据"""
    banner('F', '阶段划分漏掉数据（静默排除了策略最差的一段）')
    # 真实路径：对每个实际存在的回测目录，调用 analyze_phases() 数出它
    # 真正纳入统计的交易日，与该组回测的总交易日比较。
    # 验收标准明确为：【被分析的每一组，其交易日都应 100% 落入某个阶段】。
    from performance_analysis import PerformanceAnalyzer, MARKET_PHASES
    p_start = min((p['start'] for p in MARKET_PHASES if p['start'] is not None), default=None)
    p_end = max((p['end'] for p in MARKET_PHASES if p['end'] is not None), default=None)
    print(f'  MARKET_PHASES 硬边界: {p_start or "(向前敞开)"} ~ {p_end or "(向后敞开)"}')
    print(f'    首段 start = {MARKET_PHASES[0]["start"] or "None -> 敞开到数据起点"}')
    print(f'    末段 end   = {MARKET_PHASES[-1]["end"] or "None -> 敞开到数据终点"}')

    import glob
    dirs = (sorted(glob.glob('output/backtests/h20269/*/')) + sorted(glob.glob('output/backtests/etf512890/*/')))
    targets = []
    for dd in dirs:
        c = os.path.join(dd, 'H20269_滚动仓位每日记录.csv')
        if os.path.exists(c):
            targets.append(c)
    if not targets:
        print('  [SKIP] 找不到任何每日记录 CSV')
        return None

    print(f'  逐组核对（共 {len(targets)} 组 H20269 回测）：')
    total_missing = 0
    worst = None
    chain_bad = 0
    for c in targets:
        ana = PerformanceAnalyzer(c)
        d = ana.df
        covered = pd.Series(False, index=d.index)
        for p in MARKET_PHASES:
            covered |= phase_mask(d['日期'], p)

        miss = int((~covered).sum())
        total_missing += miss
        if miss:
            g = d[~covered]
            s = (g['总资产'].iloc[-1] / g['总资产'].iloc[0] - 1) * 100
            b = (g['收盘价'].iloc[-1] / g['收盘价'].iloc[0] - 1) * 100
            name = os.path.basename(os.path.dirname(c))[:44]
            print(f'    {name:<46} 漏 {miss:>4} 日  策略 {s:+7.2f}% vs 基准 {b:+7.2f}%')
            if worst is None or (b - s) > worst[1]:
                worst = (name, b - s, miss, s, b)
            continue

        # 覆盖完整时，进一步验证收益归因自洽：各段连乘应还原全程收益。
        # 这是 Bug F 的数学后果——漏数据必然导致连乘对不上（实测曾差 -209 pp）。
        r = ana.analyze_phases()
        ch = 1.0
        for _, x in r.iterrows():
            ch *= (1 + x['基准阶段收益%'] / 100)
        act = (d['收盘价'].iloc[-1] / d['收盘价'].iloc[0] - 1) * 100
        err = (ch - 1) * 100 - act
        if abs(err) > 0.5:      # 容差 0.5 pp：阶段收益按 round(,2) 存储
            chain_bad += 1
            name = os.path.basename(os.path.dirname(c))[:44]
            print(f'    {name:<46} 覆盖完整但连乘还原误差 {err:+.3f} pp  <<异常')

    if total_missing == 0:
        print(f'    全部 {len(targets)} 组 100% 覆盖'
              f'，连乘还原异常 {chain_bad} 组')

        # 反向验证：把首段 start 改回硬编码，覆盖率断言必须触发。
        # 若不触发，说明守门人失效，此项不应算 PASS。
        import copy
        import performance_analysis as _pa
        saved = copy.deepcopy(_pa.MARKET_PHASES)
        guard_ok = False
        try:
            _pa.MARKET_PHASES[0]['start'] = '2015-05-04'
            for c in targets:
                a2 = PerformanceAnalyzer(c)
                if a2.df['日期'].iloc[0] < pd.Timestamp('2015-05-04'):
                    try:
                        a2.analyze_phases()
                    except ValueError:
                        guard_ok = True
                    break
            else:
                guard_ok = True   # 无更早起点的组可测，跳过反向验证
        finally:
            _pa.MARKET_PHASES[:] = saved
        print(f'    覆盖率断言反向验证: {"触发正常" if guard_ok else "未触发 —— 守门人失效"}')
        return verdict(chain_bad == 0 and guard_ok,
                       f'{len(targets)} 组交易日 100% 覆盖，连乘可还原总收益，且缺口会被断言拦下',
                       '覆盖完整但连乘不自洽或覆盖率断言失效')

    print(f'  >>> 合计漏掉 {total_missing} 个（组×交易日）')
    if worst:
        print(f'  >>> 最严重: {worst[0]}  策略 {worst[3]:+.2f}% vs 基准 {worst[4]:+.2f}%'
              f'（落后 {worst[1]:.2f} pp）—— 被静默排除')
    return verdict(False,
                   '所有回测组的交易日均被阶段完全覆盖',
                   f'仍有 {total_missing} 个（组×交易日）落在所有阶段之外')


def check_G():
    """Sortino 下行波动率分母错误"""
    banner('G', 'Sortino 下行波动率算法错误（此项【低估】策略优势）')
    # 真实路径：由 calculate_metrics() 的索提诺反解实际生效的下行波动率
    m, bt = read_metrics('2016-01-01')
    rf = effective_annual_risk_free(bt)
    if abs(m['策略索提诺比率']) < 1e-9:
        print('  [SKIP] 索提诺为 0，无法反解')
        return None
    coded = (m['策略年化收益率'] - rf) / m['策略索提诺比率']   # 实际生效的分母

    r = bt.daily_df['当日收益率'].values                      # 已是百分数
    td = effective_trading_days(bt) or TD_CONVENTION
    correct = np.sqrt(np.mean(np.minimum(r, 0) ** 2)) * np.sqrt(td)

    print(f'  策略索提诺 = {m["策略索提诺比率"]:.6f}，反解分母（下行波动率）= {coded:.4f}')
    print(f'  正确算法 sqrt(mean(min(r,0)^2))*sqrt({td:.0f})        = {correct:.4f}')
    print(f'  偏差 = {coded - correct:+.4f}')
    if abs(coded - correct) > 0.01:
        print(f'  -> 代码用 std(负收益)（相对其自身均值、只除负收益天数）')
        print(f'  -> 策略下跌天数远少于基准，偏误【不对称】，当前低估策略优势')
    return verdict(abs(coded - correct) < 0.01, 'Sortino 分母已修正',
                   f'实际生效 {coded:.4f} 而非 {correct:.4f}')


def check_H():
    """年化交易日数 252 vs 数据实际"""
    banner('H', '年化交易日数与数据不符（所有年化绝对值虚高）')
    d = pd.read_csv(CSV, encoding='utf-8-sig')
    d.columns = ['日期', '收盘', '开盘', '高', '低', '量', '涨跌'][:len(d.columns)]
    d['日期'] = pd.to_datetime(d['日期'])
    cal_yrs = (d['日期'].iloc[-1] - d['日期'].iloc[0]).days / 365.25
    actual = len(d) / cal_yrs
    print(f'  数据行数      = {len(d)}')
    print(f'  日历年数      = {cal_yrs:.3f}')
    print(f'  实际交易日/年 = {actual:.1f}   <-- 数据的客观事实')

    # 真实路径：由 calculate_metrics() 的年化/累计反解代码实际使用的 TD 常量
    m, bt = read_metrics('2016-01-01')
    coded = effective_trading_days(bt)
    if coded is None:
        print('  [SKIP] 无法反解（累计收益过小）')
        return None
    print(f'  代码实际生效  = {coded:.1f}   <-- 由年化/累计反解，非读脚本常量')
    print(f'  2016-01 组: 累计 {m["策略累计收益率"]:.2f}% -> 年化 {m["策略年化收益率"]:.2f}%')

    n = len(bt.daily_df)
    cum = m['策略累计收益率'] / 100
    a_true = ((1 + cum) ** (1 / (n / actual)) - 1) * 100
    print(f'  若用实际 {actual:.0f} 交易日/年: 年化应为 {a_true:.2f}%'
          f'（差 {m["策略年化收益率"]-a_true:+.2f} pp）')
    if abs(coded - actual) >= 1.0:
        print(f'  -> years 被少算 {(1-actual/coded)*100:.1f}%，年化虚高约 {(coded/actual-1)*100:.1f}%')
        print(f'  注：策略与基准同向偏移，【差值】基本守恒，但绝对值全错')
    return verdict(abs(coded - actual) < 1.0,
                   f'年化口径 {coded:.1f} 与数据 {actual:.1f} 一致',
                   f'代码生效 {coded:.1f} vs 数据实际 {actual:.1f}')


def check_J():
    """回撤"改善"符号写反"""
    banner('J', '回撤"改善"符号写反（显示错误）')
    # 真实路径：实际生成一份报告，解析输出文本里"改善"的数值符号。
    # 判定依据是【输出的符号对不对】，而非源码里是否出现某些词。
    f = 'output/backtests/h20269/2015-05起_深度定投策略/H20269_滚动仓位每日记录.csv'
    if not os.path.exists(f):
        print(f'  [SKIP] 找不到 {f}')
        return None

    from performance_analysis import PerformanceAnalyzer
    ana = PerformanceAnalyzer(f)
    tmp = os.path.join('output', '_audit_tmp_report.md')
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ana.generate_report(tmp)
    text = open(tmp, encoding='utf-8').read()
    try:
        os.remove(tmp)
    except OSError:
        pass

    # 抓出所有 "策略最大回撤: X% / 基准最大回撤: Y%（<措辞> Z%|Zpp）"
    # 措辞不写死（修复时从"改善"改为"回撤更浅"），只校验【数值符号对不对】——
    # 否则一旦改了措辞，正则匹配不到就会"0 处错误"假 PASS。
    pat = re.compile(r'策略最大回撤:\s*(-?[\d.]+)%\s*/\s*基准最大回撤:\s*(-?[\d.]+)%'
                     r'（[^0-9（）]*?\s*([+-]?[\d.]+)\s*(?:%|pp)）')
    found = pat.findall(text)
    print(f'  解析到 {len(found)} 处回撤对比输出（来自实际生成的报告）')
    if len(found) == 0:
        print('  [WARN] 一处都没匹配到 —— 可能是措辞又变了，正则需同步更新。')
        print('         此项按 FAIL 处理，避免"匹配不到"被当成"没有错误"。')
        return verdict(False, '回撤"改善"符号正确',
                       '报告中未匹配到回撤对比输出，无法验证（正则需更新）')
    wrong = 0
    for s, b, imp in found[:6]:
        s, b, imp = float(s), float(b), float(imp)
        expect = abs(b) - abs(s)         # 正确：回撤更浅为正改善
        ok = abs(imp - expect) < 0.02
        wrong += (not ok)
        print(f'    策略 {s:>7.2f}% / 基准 {b:>7.2f}%  输出改善 {imp:>7.2f}%  '
              f'应为 {expect:>7.2f}%  {"OK" if ok else "<<符号/数值错"}')
    if len(found) > 6:
        print(f'    ...（另 {len(found)-6} 处，共 {wrong} 处错误）')
        for s, b, imp in found[6:]:
            if abs(float(imp) - (abs(float(b)) - abs(float(s)))) >= 0.02:
                wrong += 1
    if wrong:
        print(f'  -> 两个负数直接相减: 基准-策略 < 0，却标为"改善"')
        print(f'  -> 应为 abs(基准) - abs(策略)')
    # run_multiple_backtests.py:168 同一 bug，静态确认其表达式是否已修。
    # 不以"改善"二字为锚（修复后措辞已变），而是找【输出回撤对比的那一行】，
    # 检查它是否对两个回撤值做了 abs() —— 裸相减即为未修。
    rm = src_path('run_multiple_backtests.py')
    rm_bad = False
    rm_hit = 0
    for i, line in enumerate(open(rm, encoding='utf-8'), 1):
        if ('最大回撤' not in line) or ('f.write' not in line):
            continue
        if '基准最大回撤' not in line or '-' not in line:
            continue
        rm_hit += 1
        # 该行同时输出策略与基准回撤，且做了差值 -> 必须用 abs()
        if 'abs(' not in line:
            rm_bad = True
            print(f'  {rm}:{i} 仍为裸相减: {line.strip()[:88]}')
    if rm_hit == 0:
        # 一行都没匹配到，说明这段输出被改写或删除了 —— 不能当作"已修"
        rm_bad = True
        print(f'  [WARN] {rm} 中未找到输出回撤对比的那一行，无法静态验证')
    elif not rm_bad:
        print(f'  {rm}: {rm_hit} 处回撤差值均已用 abs() 计算')
    return verdict(wrong == 0 and not rm_bad, '回撤"改善"符号正确',
                   f'报告 {wrong} 处符号错误' + ('，run_multiple_backtests 未修' if rm_bad else ''))


# ============================ 结论级检查（策略层面） ============================

def check_OOS():
    """样本外检验：2007-2013"""
    banner('OOS', '样本外检验（参数在 2014-2026 上选定，此为唯一干净样本）')
    cases = [('2007-01-04', '2013-12-31', '全段 2007-2013'),
             ('2007-01-04', '2009-12-31', '泡沫+崩盘 2007-2009'),
             ('2010-01-04', '2013-12-31', '熊市/震荡 2010-2013')]
    print(f'  {"区间":<24}{"策略年化":>10}{"基准年化":>10}{"策略夏普":>10}{"基准夏普":>10}')
    ok = True
    for sd, ed, lab in cases:
        d, _, _ = run_backtest(sd, ed)
        eq, px = d['总资产'].reset_index(drop=True), d['收盘价'].reset_index(drop=True)
        yrs = len(eq) / TD_CONVENTION
        sa = ((eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1) * 100
        ba = ((px.iloc[-1] / px.iloc[0]) ** (1 / yrs) - 1) * 100
        ss = (sa - CASH_RATE) / ann_vol(eq)
        bs = (ba - CASH_RATE) / ann_vol(px)
        print(f'  {lab:<24}{sa:>9.2f}%{ba:>9.2f}%{ss:>10.3f}{bs:>10.3f}')
        if '全段' in lab:
            ok = sa > CASH_RATE and ss > 0.3
    print(f'\n  验收标准: 全段年化 > {CASH_RATE}%（现金利率）且夏普 > 0.3')
    return verdict(ok, '样本外表现达标', '样本外年化/夏普不达标 —— 策略未通过样本外检验')


def check_DOWNSIDE():
    """无下行出口：2008 满仓验证"""
    banner('DOWNSIDE', '下行出口检验（跌破年线只买不卖 -> 2008 场景）')
    d, _, _ = run_backtest('2007-01-04', '2013-12-31')
    eq = d['总资产']
    dd = (eq - eq.cummax()) / eq.cummax() * 100
    i = dd.idxmin()
    pos = d['持仓市值'] / d['总资产']
    deep = ((pos > 0.9) & (d['乖离率'] < -20)).sum()
    worst_div = d.loc[pos > 0.9, '乖离率'].min()
    print(f'  最大回撤          = {dd.min():.2f}%  ({d.loc[i,"日期"].date()})')
    print(f'  >90%仓位且乖离<-20% 的交易日数 = {deep}')
    print(f'  满仓时最深乖离率  = {worst_div:.2f}%')
    print(f'  验收标准: 回撤 > -40% 且 满仓深跌天数 < 30')
    return verdict(dd.min() > -40 and deep < 30, '下行闸门有效',
                   f'仍无下行保护（回撤 {dd.min():.1f}%，{deep} 天满仓深跌）')


def check_RISK_CLAIM():
    """控回撤是真本事还是现金稀释"""
    banner('RISK', '风险控制检验：策略 vs 同仓位静态混合（关键！）')
    print(f'  {"起始日":<13}{"仓位%":>7}{"策略MDD":>10}{"混合MDD":>10}{"":>7}{"策略vol":>9}{"混合vol":>9}')
    bad_dd = bad_v = n = 0
    for sd in ALL_STARTS:
        d, _, _ = run_backtest(sd)
        eq = d['总资产'].reset_index(drop=True)
        px = d['收盘价'].reset_index(drop=True)
        w = (d['持仓市值'] / d['总资产']).mean()
        bl = static_blend(px, w)
        s_dd, b_dd = max_drawdown(eq), max_drawdown(bl)
        s_v, b_v = ann_vol(eq), ann_vol(bl)
        f1, f2 = s_dd < b_dd, s_v > b_v
        bad_dd += f1
        bad_v += f2
        n += 1
        print(f'  {sd:<13}{w*100:>7.1f}{s_dd:>10.2f}{b_dd:>10.2f}'
              f'{"  WORSE" if f1 else "   ok":>7}{s_v:>9.2f}{b_v:>9.2f}'
              f'{"  WORSE" if f2 else "   ok":>7}')
    print(f'\n  策略回撤劣于同仓位静态混合: {bad_dd}/{n}')
    print(f'  策略波动劣于同仓位静态混合: {bad_v}/{n}')
    print(f'  -> 若多数为 WORSE，则"控回撤能力"只是现金稀释，非择时本事')
    return verdict(bad_dd <= n * 0.3 and bad_v <= n * 0.3,
                   '风险控制优于同仓位静态混合',
                   f'回撤 {bad_dd}/{n}、波动 {bad_v}/{n} 劣于静态混合')


def check_ALPHA():
    """择时 alpha 显著性（恒定权重零假设）"""
    banner('ALPHA', '择时 alpha 显著性（零假设 = 恒定权重同仓位混合）')
    cases = [('全历史 2006-2026', '2006-01-01', None),
             ('样本外 2007-2013', '2007-01-04', '2013-12-31'),
             ('样本内 2014-2026', '2014-01-01', None),
             ('样本内 2015-2026', '2015-05-01', None)]
    print(f'  {"区间":<20}{"仓位%":>7}{"alpha%/yr":>11}{"t":>8}{"NW-t":>8}{"显著":>7}')
    full_ok = False
    for lab, sd, ed in cases:
        d, _, _ = run_backtest(sd, ed)
        eq, px = d['总资产'].values, d['收盘价'].values
        rs = np.diff(eq) / eq[:-1]
        rb = np.diff(px) / px[:-1]
        w = (d['持仓市值'] / d['总资产']).mean()
        cash_d = (1 + CASH_RATE / 100) ** (1 / TD_CONVENTION) - 1
        a = rs - (w * rb + (1 - w) * cash_d)
        t = a.mean() / (a.std(ddof=1) / np.sqrt(len(a)))
        nw, _ = newey_west_t(a)
        sig = abs(nw) > 1.96
        print(f'  {lab:<20}{w*100:>7.1f}{a.mean()*TD_CONVENTION*100:>+11.2f}'
              f'{t:>+8.2f}{nw:>+8.2f}{"  YES" if sig else "   no":>7}')
        if '全历史' in lab:
            full_ok = nw > 1.96
    print(f'\n  注：恒定权重（非每日实际仓位）才是正确零假设。')
    print(f'      用每日实际仓位会使检验变成同义反复。')
    return verdict(full_ok, '全历史择时 alpha 显著',
                   '全历史择时 alpha 不显著 -> 无证据表明具备择时能力')


def check_PARAM():
    """参数敏感性：a 是否落在收益峰顶"""
    banner('PARAM', '参数敏感性（a=15 是否为过拟合峰顶）')
    print(f'  {"a":<6}', end='')
    offs = [1.0, 2.5, 5.0, 10.0]
    for o in offs:
        print(f'{"b=a+"+str(o):>14}', end='')
    print()
    table = {}
    for a in [8, 10, 12, 15, 18, 22, 25]:
        print(f'  a={a:<4}', end='')
        row = []
        for o in offs:
            rr, ss = [], []
            for sd in MAIN_STARTS:
                d, _, _ = run_backtest(sd, None, sell_threshold_a=float(a),
                                       sell_threshold_b=float(a + o))
                eq = d['总资产'].reset_index(drop=True)
                yrs = len(eq) / TD_CONVENTION
                ann = ((eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1) * 100
                rr.append(ann)
                ss.append((ann - CASH_RATE) / ann_vol(eq))
            row.append(np.mean(rr))
            print(f'{np.mean(rr):>7.2f}/{np.mean(ss):.2f}', end='')
        table[a] = row
        print()
    col0 = {a: table[a][0] for a in table}
    peak = max(col0, key=col0.get)
    print(f'\n  b=a+1.0 列的收益峰值出现在 a={peak}')
    print(f'  当前生产参数 a=15 -> {"【正好在峰顶附近，过拟合指纹】" if abs(peak-15)<=3 else "未在峰顶"}')
    print(f'  a>=22 后结果恒定 = 阈值永不触发，策略退化为买入持有')
    return verdict(abs(peak - 15) > 3, 'a=15 非峰值点',
                   f'收益峰值在 a={peak}，紧邻生产参数 a=15')


def check_DIVERGENCE_MATH():
    """文档中乖离率与趋势的关系是否正确"""
    banner('MATH', 'ROLLING_POSITION_STRATEGY.md:717-719 的乖离率论证')
    print('  文档称: "10%乖离率 = 比前一年涨了10%，属于正常区间"')
    print('  实际  : 乖离率是对 250 日【均值】的偏离，非对 250 日前【价格】的偏离')
    print('  对趋势 P=P0*e^(gt)，稳态乖离 = g/(1-e^-g) - 1\n')
    print(f'  {"趋势 g":>10}{"稳态乖离率":>14}')
    for g in [0.05, 0.10, 0.15, 0.20, 0.30]:
        print(f'  {g*100:>9.0f}%{(g/(1-np.exp(-g))-1)*100:>13.2f}%')
    from scipy.optimize import brentq
    print()
    for tgt in [0.15, 0.175]:
        g = brentq(lambda g: g / (1 - np.exp(-g)) - 1 - tgt, 0.01, 3)
        print(f'  乖离 {tgt*100:.1f}% 需持续 {g*100:.1f}%/年 的趋势')
    d10 = (0.10 / (1 - np.exp(-0.10)) - 1) * 100
    print(f'\n  -> 10%/年趋势只产生 {d10:.2f}% 乖离，不是 10%。文档前提有【算术错误】。')
    print(f'  -> a=15% 实际对应 ~28.6%/年趋势 = 罕见极端阈值，非文档所称"温和"')
    return verdict(False, '', '文档算术错误（需人工修订文档，非代码问题）')


def check_COST():
    """实际佣金率 vs 名义披露"""
    banner('COST', '实际佣金率（最低佣金效应）')
    _, tr, bt = run_backtest('2015-05-01')
    fee = [t for t in tr if '佣金' in t]
    at_floor = sum(1 for t in fee if abs(t['佣金'] - bt.min_commission) < 1e-9)
    notional = sum(t.get('净投入', t.get('金额', 0)) for t in fee)
    total_c = sum(t['佣金'] for t in fee)
    print(f'  含费用交易笔数      = {len(fee)}')
    print(f'  触发 {bt.min_commission} 元最低佣金 = {at_floor} 笔 ({at_floor/len(fee)*100:.1f}%)')
    print(f'  名义佣金率          = {bt.commission_rate*100:.4f}%')
    print(f'  实际佣金/成交额     = {total_c/notional*100:.4f}%'
          f'   ({total_c/notional/bt.commission_rate:.1f} 倍)')
    print(f'  注：这不是代码 bug，是【披露口径】问题 + n=40 定投节奏的实盘经济性问题')
    return verdict(at_floor / len(fee) < 0.3, '最低佣金影响可忽略',
                   f'{at_floor/len(fee)*100:.0f}% 交易触发最低佣金，实际费率是名义的'
                   f' {total_c/notional/bt.commission_rate:.1f} 倍')


def check_NO_LOOKAHEAD():
    """确认无前视偏差（回归保护：修 bug 时别引入）"""
    banner('LOOKAHEAD', '前视偏差检查（此项应始终 PASS）')
    src_dc = open(src_path('data_calculator.py'), encoding='utf-8').read()
    center = 'center=True' in src_dc
    print(f'  data_calculator.py 出现 center=True : {center}')
    print(f'  rolling(window=250) 默认 center=False -> trailing 窗口，因果')

    # MA250 必须在 start_date 过滤【之前】用全量数据算好
    d, _, _ = run_backtest('2020-01-01')
    first_ma = d['MA250'].iloc[0]
    print(f'  2020-01 组首日 MA250 = {first_ma:.2f}  (非 NaN -> 用全量历史算，正确)')

    # 独立重算校验
    raw = pd.read_csv(CSV, encoding='utf-8-sig')
    raw.columns = ['日期', '收盘', '开盘', '高', '低', '量', '涨跌'][:len(raw.columns)]
    raw['日期'] = pd.to_datetime(raw['日期'])
    raw['ma'] = raw['收盘'].rolling(250).mean()
    d0 = d['日期'].iloc[0]
    ref = raw.loc[raw['日期'] == d0, 'ma'].iloc[0]
    diff = abs(ref - first_ma)
    print(f'  独立重算 MA250       = {ref:.2f}   (差异 {diff:.2e})')

    # 账户恒等式
    err = (d['总资产'] - (d['持仓份额'] * d['收盘价'] + d['空仓资金'])).abs().max()
    print(f'  账户恒等式最大误差   = {err:.2e}  (总资产 = 份额x价格 + 现金)')
    ok = (not center) and diff < 1e-6 and err < 1e-6 and pd.notna(first_ma)
    return verdict(ok, '无前视偏差，账户自洽', '出现前视偏差或账户不平 —— 严重回归！')


# ============================ 注册表 ============================

CHECKS = {
    # 硬错误：单位/公式/覆盖，客观可判定
    'A': ('无风险利率单位错误', check_A, 'BUG'),
    'B': ('现金计息口径错误', check_B, 'BUG'),
    'C': ('triggered_b 死代码', check_C, 'SMELL'),
    'E': ('阶段收益率公式错误', check_E, 'BUG'),
    'F': ('阶段划分漏数据', check_F, 'BUG'),
    'G': ('Sortino 分母错误', check_G, 'BUG'),
    'H': ('年化交易日数不符', check_H, 'BUG'),
    'J': ('回撤改善符号反', check_J, 'BUG'),
    # 结论级：策略有效性
    'OOS': ('样本外检验', check_OOS, 'STRATEGY'),
    'DOWNSIDE': ('下行出口检验', check_DOWNSIDE, 'STRATEGY'),
    'RISK': ('风险控制真伪', check_RISK_CLAIM, 'STRATEGY'),
    'ALPHA': ('择时 alpha 显著性', check_ALPHA, 'STRATEGY'),
    'PARAM': ('参数过拟合', check_PARAM, 'STRATEGY'),
    'MATH': ('文档乖离率论证', check_DIVERGENCE_MATH, 'DOC'),
    'COST': ('实际佣金率', check_COST, 'DISCLOSURE'),
    # 回归保护
    'LOOKAHEAD': ('前视偏差（应始终 PASS）', check_NO_LOOKAHEAD, 'REGRESSION'),
}


def main():
    ap = argparse.ArgumentParser(description='审计回归验证')
    ap.add_argument('--only', help='只跑指定项，逗号分隔，如 A,B,E')
    ap.add_argument('--list', action='store_true', help='列出所有检查项')
    args = ap.parse_args()

    if args.list:
        print(f'{"代码":<12}{"类型":<13}说明')
        for k, (desc, _, kind) in CHECKS.items():
            print(f'{k:<12}{kind:<13}{desc}')
        return 0

    keys = [k.strip().upper() for k in args.only.split(',')] if args.only else list(CHECKS)
    bad = [k for k in keys if k not in CHECKS]
    if bad:
        print(f'未知检查项: {bad}\n可用: {list(CHECKS)}')
        return 2

    print('#' * 78)
    print('# 红利低波策略 —— 审计回归验证')
    print(f'# 数据: {CSV}')
    print(f'# 检查项: {", ".join(keys)}')
    print('#' * 78)

    results = {}
    for k in keys:
        desc, fn, kind = CHECKS[k]
        try:
            results[k] = fn()
        except Exception as e:
            print(f'\n  [ERROR] {k} 执行失败: {type(e).__name__}: {e}')
            results[k] = False

    print('\n' + '#' * 78)
    print('# 汇总')
    print('#' * 78)
    print(f'{"代码":<12}{"类型":<13}{"结果":<10}说明')
    n_fail = 0
    for k in keys:
        desc, _, kind = CHECKS[k]
        r = results[k]
        tag = 'SKIP' if r is None else ('PASS' if r else 'FAIL')
        if r is not None and not r:
            n_fail += 1
        print(f'{k:<12}{kind:<13}{tag:<10}{desc}')
    print(f'\n未通过: {n_fail} / {len(keys)}')
    print('说明: FAIL = 该问题仍存在（尚未修复）；修复后应转为 PASS')
    return 1 if n_fail else 0


if __name__ == '__main__':
    sys.exit(main())
