# -*- coding: utf-8 -*-
"""构建【改前】源码副本（反向补丁）

原则：每处替换都必须命中且仅命中一次，否则立即报错退出 —— 保证重建
出的 legacy 版本忠实对应本次会话前的代码，而非我手写的近似品。
"""
import sys, os, shutil, argparse
sys.stdout.reconfigure(encoding='utf-8')

_ap = argparse.ArgumentParser()
_ap.add_argument('--keep', default='', help='保留修复的 bug 字母，逗号分隔；其余全部还原')
_ap.add_argument('--dst', default='legacy')
_A = _ap.parse_args()
KEEP = set(x.strip().upper() for x in _A.keep.split(',') if x.strip())

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
DST  = os.path.join(ROOT, 'tools', 'ab_compare', _A.dst)

os.makedirs(DST, exist_ok=True)

# 重构后 core/ 里的文件顶部有 PROJECT-ROOT BOOTSTRAP 前言，它按
# 「上两级目录」推断项目根 —— 对 core/x.py 正确，但副本落在
# tools/ab_compare/<变体>/x.py 时会算成 tools/，进而 chdir 到 tools/，
# 导致读不到 data/ 也写不到 output/。故复制时必须剥掉这段前言：
# run_ab.py 自己已负责 sys.path 与 chdir。
_BEG = '# === PROJECT-ROOT BOOTSTRAP ==='
_END = '# === /PROJECT-ROOT BOOTSTRAP ===\n'


def strip_bootstrap(s, fn):
    if _BEG not in s:
        return s
    i = s.index(_BEG)
    j = s.index(_END, i) + len(_END)
    print(f'  [STRIP] {fn} / 剥离 PROJECT-ROOT BOOTSTRAP 前言')
    return s[:i] + s[j:]


for fn in ['rolling_position_backtest.py', 'performance_analysis.py',
           'data_calculator.py']:
    src = open(os.path.join(ROOT, 'core', fn), encoding='utf-8').read()
    open(os.path.join(DST, fn), 'w', encoding='utf-8').write(
        strip_bootstrap(src, fn))

def patch(fn, pairs):
    p = os.path.join(DST, fn)
    s = open(p, encoding='utf-8').read()
    for tag, old, new in pairs:
        if tag.split()[0].upper() in KEEP:
            print(f'  [KEEP] {fn} / {tag}  <- 保留修复')
            continue
        n = s.count(old)
        if n != 1:
            print(f'  [FATAL] {fn} / {tag}: 命中 {n} 次（应为 1），中止')
            sys.exit(1)
        s = s.replace(old, new)
        print(f'  [OK] {fn} / {tag}')
    open(p, 'w', encoding='utf-8').write(s)

print('反向补丁：rolling_position_backtest.py')
patch('rolling_position_backtest.py', [

 # ---- Bug H：还原硬编码 252 ----
 ('H 年化交易日数 -> 252',
  """        _cal_years = (df['日期'].iloc[-1] - df['日期'].iloc[0]).days / 365.25
        if _cal_years > 0:
            TRADING_DAYS_PER_YEAR = len(df) / _cal_years
        else:
            TRADING_DAYS_PER_YEAR = 243.0     # 单日等退化样本的兜底""",
  """        TRADING_DAYS_PER_YEAR = 252"""),

 # ---- Bug A：还原 daily x 252 ----
 ('A 无风险利率 -> daily*252',
  """        annual_risk_free = self.cash_return_rate""",
  """        daily_risk_free = self.calculate_daily_return(self.cash_return_rate)
        annual_risk_free = daily_risk_free * TRADING_DAYS_PER_YEAR * 100"""),

 # ---- Bug B：还原每交易日只计一天利息 ----
 ('B 现金计息 -> 每交易日一天',
  """            if i > 0:
                elapsed_days = (current_date - self.df.loc[i - 1, '日期']).days
                cash *= (1 + daily_cash_return) ** elapsed_days""",
  """            cash += cash * daily_cash_return"""),

 # ---- Bug G：还原 std(负收益)（策略侧）----
 ('G 策略下行波动 -> std(负收益)',
  """        downside_volatility = self.calculate_downside_volatility(
            daily_returns, TRADING_DAYS_PER_YEAR)""",
  """        negative_returns = daily_returns[daily_returns < 0]
        downside_volatility = np.std(negative_returns) * np.sqrt(TRADING_DAYS_PER_YEAR) if len(negative_returns) > 0 else 0"""),

 # ---- Bug G：还原 std(负收益)（基准侧）----
 ('G 基准下行波动 -> std(负收益)',
  """        benchmark_downside_vol = self.calculate_downside_volatility(
            benchmark_daily_returns, TRADING_DAYS_PER_YEAR)""",
  """        benchmark_negative = benchmark_daily_returns[benchmark_daily_returns < 0]
        benchmark_downside_vol = np.std(benchmark_negative) * np.sqrt(TRADING_DAYS_PER_YEAR) if len(benchmark_negative) > 0 else 0"""),

 # ---- Bug D：还原买入也征印花税 ----
 ('D 买入征印花税',
  """        # 先按比例算（假设未触发最低佣金）
        gross = invest_amount / (1 + self.commission_rate)
        commission = gross * self.commission_rate

        if commission < self.min_commission:
            # 触发最低佣金，重算
            commission = self.min_commission
            # 防御：若 invest_amount 连最低佣金都不够，直接返回（视为费用吞噬）
            if invest_amount <= self.min_commission:
                return 0.0, invest_amount, 0.0
            gross = invest_amount - self.min_commission

        return gross, commission, 0.0""",
  """        total_rate = self.commission_rate + self.stamp_duty_rate
        gross = invest_amount / (1 + total_rate)
        commission = gross * self.commission_rate

        if commission < self.min_commission:
            commission = self.min_commission
            if invest_amount <= self.min_commission:
                return 0.0, invest_amount, 0.0
            gross = (invest_amount - self.min_commission) / (1 + self.stamp_duty_rate)

        stamp_duty = gross * self.stamp_duty_rate
        return gross, commission, stamp_duty"""),

 # ---- Bug D：还原卖出用名义税率（ETF 也征）----
 ('D 卖出 ETF 不免征',
  """        stamp_duty = gross_proceeds * self.effective_stamp_duty_rate""",
  """        stamp_duty = gross_proceeds * self.stamp_duty_rate"""),
])

print('反向补丁：performance_analysis.py')
patch('performance_analysis.py', [

 # ---- Bug F：还原首段硬边界 ----
 ('F 首段 start -> 2015-05-04',
  """        'start': None, 'end': '2015-09-30',""",
  """        'start': '2015-05-04', 'end': '2015-09-30',"""),

 # ---- Bug F：还原末段硬边界 ----
 ('F 末段 end -> 2026-07-20',
  """        'start': '2024-09-24', 'end': None,""",
  """        'start': '2024-09-24', 'end': '2026-07-20',"""),

 # ---- Bug F：还原无覆盖率断言的掩码 ----
 ('F 掩码 + 去断言',
  """        covered = pd.Series(False, index=self.df.index)
        for phase in MARKET_PHASES:
            # 修复 Bug F：start/end 为 None 表示向该侧数据边界敞开（不设限）。
            mask = pd.Series(True, index=self.df.index)
            if phase['start'] is not None:
                mask &= self.df['日期'] >= phase['start']
            if phase['end'] is not None:
                mask &= self.df['日期'] <= phase['end']
            covered |= mask
            seg = self.df[mask]""",
  """        for phase in MARKET_PHASES:
            mask = (self.df['日期'] >= phase['start']) & (self.df['日期'] <= phase['end'])
            seg = self.df[mask]"""),

 # ---- Bug E：还原「累计收益率末值-首值」----
 ('E 阶段收益率公式',
  """            base_i = self.df.index.get_loc(seg.index[0])
            base_i = base_i - 1 if base_i > 0 else base_i
            strategy_base = self.df['总资产'].iloc[base_i]
            benchmark_base = self.df['收盘价'].iloc[base_i]

            strategy_phase_return = (seg['总资产'].iloc[-1] / strategy_base - 1) * 100
            benchmark_phase_return = (seg['收盘价'].iloc[-1] / benchmark_base - 1) * 100
            excess = strategy_phase_return - benchmark_phase_return""",
  """            strategy_phase_return = seg['累计收益率'].iloc[-1] - seg['累计收益率'].iloc[0]
            benchmark_phase_return = seg['基准累计收益%'].iloc[-1] - seg['基准累计收益%'].iloc[0]
            excess = strategy_phase_return - benchmark_phase_return"""),
])

# 去掉覆盖率断言块（属于 Bug F）
if 'F' in KEEP:
    print('  [KEEP] performance_analysis.py / F 覆盖率断言  <- 保留修复')
    p = None
else:
    p = os.path.join(DST, 'performance_analysis.py')
if p:
    s = open(p, encoding='utf-8').read()
    i = s.find('        # 覆盖率断言（Bug F 的守门人）')
    j = s.find('        return pd.DataFrame(results)', i)
    if i < 0 or j < 0:
        print('  [FATAL] 找不到覆盖率断言块')
        sys.exit(1)
    s = s[:i] + s[j:]
    open(p, 'w', encoding='utf-8').write(s)
    print('  [OK] performance_analysis.py / F 移除覆盖率断言')

# 编译校验
import py_compile
for fn in ['rolling_position_backtest.py', 'performance_analysis.py']:
    py_compile.compile(os.path.join(DST, fn), doraise=True)
print('\n语法校验通过，legacy 版本重建完成 ->', DST)
