# -*- coding: utf-8 -*-
"""
滚动仓位策略回测程序
基于250日均线和乖离率的买卖策略
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
import pandas as pd
import numpy as np
import os
import re
from datetime import datetime
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from data_calculator import MA250DataCalculator

# Windows 控制台 UTF-8 输出（避免 GBK 编码无法显示 emoji）
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass


class RollingPositionBacktest:
    """滚动仓位策略回测器"""

    # 默认深度定投档位：按乖离率深度加倍
    # dca_tiers 按 threshold 从小到大排列
    # 命中第一个 divergence <= threshold 的档位；无命中则返回 1.0
    DEFAULT_DCA_TIERS = [(-8.0, 3.0), (-4.0, 2.0)]  # ≤-8%: 3×, ≤-4%: 2×, 其他: 1×

    def __init__(self, csv_file_path,
                 invest_days=40,
                 sell_threshold_a=15.0,
                 sell_threshold_b=17.5,
                 cash_return_rate=1.2,
                 initial_capital=100000,
                 start_date=None,
                 end_date=None,
                 dca_tiers=None,
                 lump_sum_threshold=2000.0,
                 noise_threshold=1.0,
                 enable_trading_costs=True,
                 commission_rate=0.00025,
                 stamp_duty_rate=0.0005,
                 stamp_duty_exempt=None,
                 min_commission=5.0):
        """
        初始化回测器

        参数：
        csv_file_path: CSV数据文件路径
        invest_days: 定投交易日数（n）
        sell_threshold_a: 第一卖出阈值a%（卖出50%）
        sell_threshold_b: 第二卖出阈值b%（卖出剩余50%）
        cash_return_rate: 空仓资金年化收益率c%
        initial_capital: 初始资金（默认10万）
        start_date: 回测起始日期（None=数据首日，str/datetime格式如 '2020-01-01'）
        end_date: 回测结束日期（None=数据末日，str/datetime格式如 '2024-12-31'）
        dca_tiers: 深度定投档位列表，例如 [(-8.0, 3.0), (-4.0, 2.0)]
                   传入 None 使用默认三档加倍
                   传入 [] 关闭深度定投（全1×，回退到原策略）
        lump_sum_threshold: 🆕 全仓买入阈值（元）。当 cash < 此值时，触发买入信号直接一次性
                            全仓买入，不进入 n 日定投模式（避免小资金分 40 份的荒诞定投）。
                            默认 2000 元（佣金占比 ≤ 0.25%，符合实盘最低经济性）。
        noise_threshold: 🆕 浮点噪声门槛（元）。当 cash < 此值时视为浮点残留，直接忽略信号
                         不记录任何交易。默认 1 元。
        enable_trading_costs: 🆕 是否启用交易成本建模（佣金+印花税）。默认 True。
        commission_rate: 🆕 场内交易佣金率（单边）。默认 0.00025（0.025%），买卖双向收取。
        stamp_duty_rate: 🆕 印花税率。默认 0.0005（0.05%）。
                         修复 Bug D：按 A 股实际规则【仅卖出方缴纳】，买入不征。
                         且 ETF / LOF 等基金份额【完全免征】印花税 —— 标的为基金
                         代码（如 512890、515450）时本项自动置 0，可用
                         stamp_duty_exempt 显式覆盖。
        stamp_duty_exempt: 🆕 是否免征印花税。None=按标的自动判定（基金免征，
                           指数/股票征收）；True/False=显式指定。
        min_commission: 🆕 最低佣金（元/笔）。每笔佣金 = max(成交金额 × commission_rate, 此值)。
                        默认 5 元（A 股实盘规则）。
                        注：实测 97% 的定投笔数触发此下限，使【实际】佣金率达
                        0.088%，为名义 0.025% 的 3.5 倍（见 audit_checks.py COST）。
        """
        self.csv_file_path = csv_file_path
        self.stock_name = None

        # ============ 策略参数（可修改） ============
        self.invest_days = invest_days  # n: 定投交易日数
        self.sell_threshold_a = sell_threshold_a  # a: 第一卖出阈值
        self.sell_threshold_b = sell_threshold_b  # b: 第二卖出阈值
        self.cash_return_rate = cash_return_rate  # c: 空仓年化收益率
        self.initial_capital = initial_capital  # 初始资金

        # 🆕 起止日期参数
        self.start_date = self._parse_date(start_date)
        self.end_date = self._parse_date(end_date)

        # 🆕 深度定投档位
        self.dca_tiers = list(dca_tiers) if dca_tiers is not None else list(self.DEFAULT_DCA_TIERS)

        # 🆕 小额资金处理参数
        self.lump_sum_threshold = lump_sum_threshold
        self.noise_threshold = noise_threshold

        # 🆕 交易成本参数
        self.enable_trading_costs = enable_trading_costs
        self.commission_rate = commission_rate
        self.stamp_duty_rate = stamp_duty_rate
        self.min_commission = min_commission

        # 数据计算器
        self.calculator = MA250DataCalculator(csv_file_path)
        self.stock_name = self.calculator.stock_name

        # 🆕 印花税免征判定（修复 Bug D）：ETF/LOF 等基金份额免征印花税。
        # 标的名以 5/1 开头的 6 位数字为场内基金代码（如 512890、515450）；
        # 指数代码（H20269 等）与个股则照常征收。显式传参可覆盖自动判定。
        if stamp_duty_exempt is None:
            name = str(self.stock_name or '')
            self.stamp_duty_exempt = bool(re.fullmatch(r'[15]\d{5}', name))
        else:
            self.stamp_duty_exempt = bool(stamp_duty_exempt)
        self.effective_stamp_duty_rate = (
            0.0 if self.stamp_duty_exempt else self.stamp_duty_rate)

        # 回测数据
        self.df = None
        self.trading_records = []  # 交易记录

    @staticmethod
    def _parse_date(date_value):
        """将字符串/datetime/None 统一转换为 datetime 或 None"""
        if date_value is None:
            return None
        if isinstance(date_value, datetime):
            return date_value
        return pd.to_datetime(date_value)

    def _get_dca_multiplier(self, divergence):
        """
        🆕 根据当日乖离率查询深度定投倍数

        参数：
        divergence: 当日乖离率（%）

        返回：
        倍数（float），默认 1.0
        """
        for threshold, multiplier in self.dca_tiers:
            if divergence <= threshold:
                return multiplier
        return 1.0

    def _apply_buy_costs(self, invest_amount):
        """
        🆕 计算买入的实际成本分摊

        语义：invest_amount 是"从 cash 扣的总额"（含费用）。
        反算实际用于买份额的金额（gross），并计算佣金、印花税。

        修复 Bug D：买入【不缴印花税】（A 股印花税仅向卖方征收），故此处
        印花税恒为 0，公式中也不再含 stamp_duty_rate。

        公式（未触发最低佣金）：
            invest_amount = gross × (1 + commission_rate)
        公式（触发最低佣金，即 gross × commission_rate < min_commission）：
            invest_amount = gross + min_commission

        参数：
        invest_amount: 从 cash 扣的总额

        返回：
        tuple (gross, commission, stamp_duty)
        - gross: 实际用于买份额的金额
        - commission: 佣金（已考虑最低门槛）
        - stamp_duty: 印花税（买入恒为 0）
        """
        if not self.enable_trading_costs or invest_amount <= 0:
            return invest_amount, 0.0, 0.0

        # 先按比例算（假设未触发最低佣金）
        gross = invest_amount / (1 + self.commission_rate)
        commission = gross * self.commission_rate

        if commission < self.min_commission:
            # 触发最低佣金，重算
            commission = self.min_commission
            # 防御：若 invest_amount 连最低佣金都不够，直接返回（视为费用吞噬）
            if invest_amount <= self.min_commission:
                return 0.0, invest_amount, 0.0
            gross = invest_amount - self.min_commission

        return gross, commission, 0.0

    def _apply_sell_costs(self, gross_proceeds):
        """
        🆕 计算卖出的实际到账

        语义：gross_proceeds 是"毛收入"（sell_shares × price）。
        扣除佣金和印花税后得到 net_proceeds 入 cash。

        修复 Bug D：印花税仅在【卖出】时征收，且 ETF/LOF 等基金份额免征
        （用 effective_stamp_duty_rate，见 __init__ 的自动判定）。

        参数：
        gross_proceeds: 毛收入

        返回：
        tuple (net_proceeds, commission, stamp_duty)
        - net_proceeds: 实际入 cash 的金额
        """
        if not self.enable_trading_costs or gross_proceeds <= 0:
            return gross_proceeds, 0.0, 0.0

        commission = max(gross_proceeds * self.commission_rate, self.min_commission)
        stamp_duty = gross_proceeds * self.effective_stamp_duty_rate
        net_proceeds = gross_proceeds - commission - stamp_duty
        return net_proceeds, commission, stamp_duty

    def _execute_lump_sum_buy(self, cash, shares, current_date, current_price,
                               current_divergence, reason):
        """
        🆕 执行一次性全仓买入（用于 cash < lump_sum_threshold 的场景）

        参数：
        cash: 当前空仓资金
        shares: 当前持仓份额
        current_date: 当前日期
        current_price: 当前价格
        current_divergence: 当前乖离率
        reason: 触发原因（用于操作名后缀，如 '快照启动'、'强制重置'、'跌破年线'、'定投终止'）

        返回：
        tuple (new_cash, new_shares, trade_or_None)
        - 若 cash < noise_threshold：返回 (cash, shares, None)（忽略浮点噪声）
        - 否则：返回 (0, shares + buy_shares, trade_dict)
        """
        if cash < self.noise_threshold:
            # 浮点噪声，忽略信号不记录
            return cash, shares, None

        # 🆕 应用交易成本：invest_amount = cash（从 cash 扣的总额），反算 gross
        gross, commission, stamp_duty = self._apply_buy_costs(cash)
        buy_shares = gross / current_price
        new_shares = shares + buy_shares
        # 🆕 累加交易成本
        self.cumulative_commission += commission
        self.cumulative_stamp_duty += stamp_duty
        trade = {
            '日期': current_date,
            '操作': f'全仓买入({reason})',
            '价格': current_price,
            '倍数': 1.0,  # 全仓买入不区分倍数
            '计划金额': cash,
            '实际金额': cash,
            '份额': buy_shares,
            '剩余天数': 0,
            '剩余资金': 0.0,
            '乖离率': current_divergence,
            '佣金': commission,  # 🆕
            '印花税': stamp_duty,  # 🆕
            '净投入': gross,  # 🆕 实际用于买份额的金额
            '触发条件': f'cash({cash:.2f}元) < 阈值({self.lump_sum_threshold}元)，一次性全仓买入'
        }
        return 0.0, new_shares, trade

    def load_data(self):
        """加载并计算所有需要的数据"""
        print("="*60)
        print("加载回测数据")
        print("="*60)

        # 使用数据计算器（仍计算全量数据的MA250/乖离率）
        self.df, _, _, _, _ = self.calculator.run_calculations()

        if self.df is None:
            return False

        print(f"全量数据加载成功，共 {len(self.df)} 条记录")
        print(f"全量数据日期范围: {self.df['日期'].min()} 至 {self.df['日期'].max()}")

        # 🆕 按起止日期过滤
        original_count = len(self.df)
        if self.start_date is not None:
            self.df = self.df[self.df['日期'] >= self.start_date].reset_index(drop=True)
            print(f"应用起始日期过滤 {self.start_date.strftime('%Y-%m-%d')}：保留 {len(self.df)} 条")
        if self.end_date is not None:
            self.df = self.df[self.df['日期'] <= self.end_date].reset_index(drop=True)
            print(f"应用结束日期过滤 {self.end_date.strftime('%Y-%m-%d')}：保留 {len(self.df)} 条")

        filtered_count = len(self.df)
        if filtered_count == 0:
            print(f"❌ 错误：日期过滤后无数据（原 {original_count} 条）")
            return False
        if filtered_count < original_count:
            print(f"日期过滤完成：{original_count} → {filtered_count} 条")

        print(f"回测数据日期范围: {self.df['日期'].min()} 至 {self.df['日期'].max()}")
        return True

    def calculate_daily_return(self, cash_return_rate):
        """
        计算每日收益率

        参数：
        cash_return_rate: 年化收益率

        返回：
        每日收益率
        """
        # 每日收益率 = (1 + 年化收益率)^(1/365) - 1
        daily_return = (1 + cash_return_rate / 100) ** (1 / 365) - 1
        return daily_return

    def run_backtest(self):
        """运行回测"""
        if self.df is None:
            print("请先加载数据")
            return False

        print("\n" + "="*60)
        print("开始回测")
        print("="*60)

        # 打印策略参数
        print(f"\n策略参数：")
        print(f"  初始资金: {self.initial_capital:,.0f} 元")
        print(f"  定投天数(n): {self.invest_days} 个交易日")
        print(f"  第一卖出阈值(a): {self.sell_threshold_a}%")
        print(f"  第二卖出阈值(b): {self.sell_threshold_b}%")
        print(f"  空仓年化收益率(c): {self.cash_return_rate}%")
        print(f"  🆕 起始日期: {self.start_date.strftime('%Y-%m-%d') if self.start_date else '数据首日'}")
        print(f"  🆕 结束日期: {self.end_date.strftime('%Y-%m-%d') if self.end_date else '数据末日'}")
        print(f"  🆕 深度定投档位: {self.dca_tiers if self.dca_tiers else '关闭（全1×）'}")
        print(f"  🆕 全仓买入阈值: {self.lump_sum_threshold} 元（cash<此值时一次性买入）")
        print(f"  🆕 浮点噪声门槛: {self.noise_threshold} 元（cash<此值时忽略信号）")
        if self.enable_trading_costs:
            _sd = ('免征（ETF/基金）' if self.stamp_duty_exempt
                   else f'{self.stamp_duty_rate*100:.4f}% 仅卖出')
            print(f"  🆕 交易成本: 启用（佣金 {self.commission_rate*100:.4f}% 双边 + 印花税 {_sd}，最低佣金 {self.min_commission} 元/笔）")
        else:
            print(f"  🆕 交易成本: 关闭")

        # 初始化状态变量
        cash = self.initial_capital  # 空仓资金
        shares = 0.0  # 持仓份额
        total_assets = self.initial_capital  # 总资产

        # 买入状态
        is_investing = False  # 是否正在定投
        remaining_days = 0  # 剩余定投天数
        base_daily_amount = 0  # 🆕 固定基础每日金额（替代原 daily_invest_amount）

        # 卖出状态
        triggered_a = False  # 是否触发过a%卖出
        # 修复 Bug C：删除 triggered_b。
        # 它曾被初始化为 False、并在两处"周期结束"时又赋值 False，但【从未被设为 True】——
        # 因此在 4a / 4c 的判断中它是恒真项（`not triggered_b` 永远成立），是死代码。
        # 策略文档（ROLLING_POSITION_STRATEGY.md:296-297）称清仓时应置 True，但那两处
        # 紧接着就"立即重置所有状态"，True 永远无法被下一次循环观测到 —— 即「实现它」与
        # 「删除它」对策略行为完全等价。故选择删除，消除状态机的名不副实。
        # 已用 16 组回测验证：删除前后全部指标逐位相同（见 progress.md 0.22）。

        # 🆕 交易成本累计（用 self 属性，便于辅助方法访问）
        self.cumulative_commission = 0.0
        self.cumulative_stamp_duty = 0.0

        # 每日收益率（按【日历日】定义：(1+c)^(1/365)-1）
        daily_cash_return = self.calculate_daily_return(self.cash_return_rate)

        # 交易记录
        trades = []
        daily_records = []

        # 每日循环
        for i in range(len(self.df)):
            current_date = self.df.loc[i, '日期']
            current_price = self.df.loc[i, '收盘']
            current_ma250 = self.df.loc[i, 'MA250']
            current_divergence = self.df.loc[i, '乖离率']

            # 计算空仓资金利息
            # 修复 Bug B：原为 cash += cash * daily_cash_return，即每个【交易日】
            # 只计一天利息，而 daily_cash_return 是按【日历日】定义的 —— 周末与
            # 节假日的利息凭空消失，一年只计约 243 天而非 365 天。实测 283 个
            # 交易日的空仓段只赚到 0.7933%（意图 1.2% 的 66.1%）。
            # 正确做法：按距上一交易日实际经过的日历天数复利计息。首日不计息
            # （资金当日才入账）。
            if i > 0:
                elapsed_days = (current_date - self.df.loc[i - 1, '日期']).days
                cash *= (1 + daily_cash_return) ** elapsed_days

            # 更新持仓市值
            position_value = shares * current_price
            total_assets = cash + position_value

            # 记录当日状态
            daily_record = {
                '日期': current_date,
                '收盘价': current_price,
                'MA250': current_ma250,
                '乖离率': current_divergence,
                '空仓资金': cash,
                '持仓份额': shares,
                '持仓市值': position_value,
                '总资产': total_assets,
                '当日收益率': 0,
                '累计收益率': (total_assets - self.initial_capital) / self.initial_capital * 100,
                '累计佣金': self.cumulative_commission,  # 🆕
                '累计印花税': self.cumulative_stamp_duty,  # 🆕
                '累计交易成本': self.cumulative_commission + self.cumulative_stamp_duty,  # 🆕
                # 🔧 修复 Bug K：此处只能放【哨兵值】，不能放 '空仓'。
                # 旧代码默认填 '空仓'，而它只在当日真的发生交易时才被覆盖 ——
                # 于是所有"持有不动"的日子都被标成"空仓"，哪怕满仓持有。
                # 真实标签在步骤7（所有交易逻辑跑完、shares 已确定）统一回填。
                '操作': '',
                '备注': ''
            }

            # === 🆕 步骤0：快照启动（仅首日 i=0）===
            # 起始日若 close ≤ MA250，直接开始定投（不依赖前日数据）
            if i == 0 and not is_investing and current_price <= current_ma250:
                if cash < self.lump_sum_threshold:
                    # 🆕 资金低于阈值：一次性全仓买入
                    new_cash, new_shares, trade = self._execute_lump_sum_buy(
                        cash, shares, current_date, current_price,
                        current_divergence, '快照启动'
                    )
                    if trade is not None:
                        cash, shares = new_cash, new_shares
                        trades.append(trade)
                        print(f"  {current_date.strftime('%Y-%m-%d')}: 🆕 快照启动+全仓买入：cash={trade['计划金额']:.2f}元 < 阈值{self.lump_sum_threshold}元，一次性买入{trade['份额']:.4f}份")
                        daily_record['操作'] = '快照启动+全仓买入'
                        daily_record['备注'] = f'起始日跌破年线且cash({trade['计划金额']:.2f})<阈值，一次性全仓'
                    else:
                        # 浮点噪声忽略
                        daily_record['操作'] = '快照启动(忽略噪声)'
                        daily_record['备注'] = f'起始日跌破年线但cash={cash:.4f}元为浮点噪声，忽略'
                else:
                    # 资金充足：原 40 日定投逻辑
                    is_investing = True
                    remaining_days = self.invest_days
                    base_daily_amount = cash / remaining_days if remaining_days > 0 else 0

                    trade = {
                        '日期': current_date,
                        '操作': '快照启动+开始定投',
                        '价格': current_price,
                        '定投天数': self.invest_days,
                        '每日基础金额': base_daily_amount,
                        '触发条件': f'起始日close≤MA250（乖离率{current_divergence:.2f}%）'
                    }
                    trades.append(trade)
                    print(f"  {current_date.strftime('%Y-%m-%d')}: 🆕 快照启动：起始日已跌破年线（乖离率={current_divergence:.2f}%），直接开始{self.invest_days}日定投")

                    daily_record['操作'] = '快照启动+开始定投'
                    daily_record['备注'] = f'起始日已跌破年线，开启{self.invest_days}日定投（基础金额{base_daily_amount:,.2f}）'

            # 获取前一日数据，预计算"是否新发生跌破年线事件"
            prev_close = self.df.loc[i-1, '收盘'] if i > 0 else current_price
            prev_ma250 = self.df.loc[i-1, 'MA250'] if i > 0 else current_ma250
            is_break_below = (i > 0 and prev_close > prev_ma250 and current_price <= current_ma250)

            # === 步骤4：检查卖出信号（按优先级从高到低，每日只走一个分支）===
            sell_triggered = False

            # 4a. 特殊情况：跳过a%直接到b%（最高优先级）
            if (not triggered_a
                    and current_divergence > self.sell_threshold_b and shares > 0):
                sell_shares = shares
                sell_amount = sell_shares * current_price
                shares = 0
                # 🆕 应用交易成本
                net_proceeds, commission, stamp_duty = self._apply_sell_costs(sell_amount)
                cash += net_proceeds
                self.cumulative_commission += commission  # 🆕
                self.cumulative_stamp_duty += stamp_duty  # 🆕

                trade = {
                    '日期': current_date,
                    '操作': '清仓(跳过a%)',
                    '价格': current_price,
                    '份额': sell_shares,
                    '金额': sell_amount,
                    '乖离率': current_divergence,
                    '佣金': commission,  # 🆕
                    '印花税': stamp_duty,  # 🆕
                    '净到账': net_proceeds,  # 🆕
                    '触发条件': f'跳过a%直接到b%，乖离率{current_divergence:.2f}% > b({self.sell_threshold_b}%)'
                }
                trades.append(trade)
                print(f"  {current_date.strftime('%Y-%m-%d')}: 特殊情况清仓（跳过a%到b%），乖离率={current_divergence:.2f}%，卖出{sell_shares:.2f}份，获得{sell_amount:,.2f}元")

                sell_triggered = True
                daily_record['操作'] = '清仓(跳过a%)'
                daily_record['备注'] = f'乖离率{current_divergence:.2f}%直接超b%，一次性清仓'

                # 周期结束 → 全部重置
                is_investing = False
                remaining_days = 0
                base_daily_amount = 0
                triggered_a = False

            # 4b. 第一级卖出：a%触发（关键修复：triggered_a 设为 True，周期未结束）
            elif (not triggered_a and current_divergence > self.sell_threshold_a and shares > 0):
                sell_shares = shares * 0.5
                sell_amount = sell_shares * current_price
                shares -= sell_shares
                # 🆕 应用交易成本
                net_proceeds, commission, stamp_duty = self._apply_sell_costs(sell_amount)
                cash += net_proceeds
                self.cumulative_commission += commission  # 🆕
                self.cumulative_stamp_duty += stamp_duty  # 🆕

                trade = {
                    '日期': current_date,
                    '操作': '卖出50%',
                    '价格': current_price,
                    '份额': sell_shares,
                    '金额': sell_amount,
                    '乖离率': current_divergence,
                    '佣金': commission,  # 🆕
                    '印花税': stamp_duty,  # 🆕
                    '净到账': net_proceeds,  # 🆕
                    '触发条件': f'乖离率{current_divergence:.2f}% > a({self.sell_threshold_a}%)'
                }
                trades.append(trade)
                print(f"  {current_date.strftime('%Y-%m-%d')}: 触发第一级卖出，乖离率={current_divergence:.2f}%，卖出{sell_shares:.2f}份，获得{sell_amount:,.2f}元")

                sell_triggered = True
                daily_record['操作'] = '卖出50%'
                daily_record['备注'] = f'乖离率{current_divergence:.2f}%，triggered_a=True，周期未结束'

                # ✅ 关键修复：triggered_a=True（不是False！），周期未结束
                triggered_a = True
                # 立即停止定投
                is_investing = False
                remaining_days = 0
                base_daily_amount = 0

            # 4c. 第二级卖出：b%触发（前提：本周期已触发过 a%）
            elif (triggered_a
                    and current_divergence > self.sell_threshold_b and shares > 0):
                sell_shares = shares
                sell_amount = sell_shares * current_price
                shares = 0
                # 🆕 应用交易成本
                net_proceeds, commission, stamp_duty = self._apply_sell_costs(sell_amount)
                cash += net_proceeds
                self.cumulative_commission += commission  # 🆕
                self.cumulative_stamp_duty += stamp_duty  # 🆕

                trade = {
                    '日期': current_date,
                    '操作': '清仓',
                    '价格': current_price,
                    '份额': sell_shares,
                    '金额': sell_amount,
                    '乖离率': current_divergence,
                    '佣金': commission,  # 🆕
                    '印花税': stamp_duty,  # 🆕
                    '净到账': net_proceeds,  # 🆕
                    '触发条件': f'已触发a%，乖离率{current_divergence:.2f}% > b({self.sell_threshold_b}%)'
                }
                trades.append(trade)
                print(f"  {current_date.strftime('%Y-%m-%d')}: 触发第二级卖出（清仓），乖离率={current_divergence:.2f}%，卖出{sell_shares:.2f}份，获得{sell_amount:,.2f}元")

                sell_triggered = True
                daily_record['操作'] = '清仓'
                daily_record['备注'] = f'乖离率{current_divergence:.2f}%（先a%后b%），周期结束'

                # 周期结束 → 全部重置
                is_investing = False
                remaining_days = 0
                base_daily_amount = 0
                triggered_a = False

            # === 步骤5：检查买入信号（含强制重置）===
            if not sell_triggered and is_break_below:
                if triggered_a:
                    # 周期内触发a%后再跌破年线 → 强制重置
                    triggered_a = False  # 无论如何都重置
                    if cash < self.lump_sum_threshold:
                        # 🆕 资金低于阈值：一次性全仓买入（不开启新一轮定投）
                        new_cash, new_shares, trade = self._execute_lump_sum_buy(
                            cash, shares, current_date, current_price,
                            current_divergence, '强制重置'
                        )
                        if trade is not None:
                            cash, shares = new_cash, new_shares
                            trades.append(trade)
                            print(f"  {current_date.strftime('%Y-%m-%d')}: triggered_a期间跌破年线+全仓买入：cash={trade['计划金额']:.2f}元 < 阈值，一次性买入{trade['份额']:.4f}份")
                            daily_record['操作'] = '强制重置+全仓买入'
                            daily_record['备注'] = f'triggered_a期间跌破年线，cash({trade['计划金额']:.2f})<阈值，一次性全仓'
                        else:
                            daily_record['操作'] = '强制重置(忽略噪声)'
                            daily_record['备注'] = f'triggered_a期间跌破年线，cash={cash:.4f}元为浮点噪声，忽略'
                    else:
                        # 资金充足：原 40 日定投逻辑
                        is_investing = True
                        remaining_days = self.invest_days
                        base_daily_amount = cash / remaining_days if remaining_days > 0 else 0

                        trade = {
                            '日期': current_date,
                            '操作': '强制重置+开始定投',
                            '价格': current_price,
                            '定投天数': self.invest_days,
                            '每日基础金额': base_daily_amount,
                            '触发条件': 'triggered_a期间跌破年线，强制重置'
                        }
                        trades.append(trade)
                        print(f"  {current_date.strftime('%Y-%m-%d')}: triggered_a期间跌破年线，强制重置，立即开启新一轮{self.invest_days}日定投")

                        daily_record['操作'] = '强制重置+开始定投'
                        daily_record['备注'] = f'triggered_a期间跌破年线，新一轮{self.invest_days}日定投（基础金额{base_daily_amount:,.2f}）'
                elif not is_investing:
                    # 正常开始定投
                    if cash < self.lump_sum_threshold:
                        # 🆕 资金低于阈值：一次性全仓买入（不进入定投模式）
                        new_cash, new_shares, trade = self._execute_lump_sum_buy(
                            cash, shares, current_date, current_price,
                            current_divergence, '跌破年线'
                        )
                        if trade is not None:
                            cash, shares = new_cash, new_shares
                            trades.append(trade)
                            print(f"  {current_date.strftime('%Y-%m-%d')}: 跌破年线+全仓买入：cash={trade['计划金额']:.2f}元 < 阈值{self.lump_sum_threshold}元，一次性买入{trade['份额']:.4f}份")
                            daily_record['操作'] = '全仓买入(跌破年线)'
                            daily_record['备注'] = f'乖离率{current_divergence:.2f}%，cash({trade['计划金额']:.2f})<阈值，一次性全仓'
                        else:
                            daily_record['操作'] = '忽略信号(浮点噪声)'
                            daily_record['备注'] = f'乖离率{current_divergence:.2f}%，但cash={cash:.4f}元为浮点噪声，忽略'
                    else:
                        # 资金充足：原 40 日定投逻辑
                        is_investing = True
                        remaining_days = self.invest_days
                        base_daily_amount = cash / remaining_days if remaining_days > 0 else 0

                        trade = {
                            '日期': current_date,
                            '操作': '开始定投',
                            '价格': current_price,
                            '定投天数': self.invest_days,
                            '每日基础金额': base_daily_amount,
                            '触发条件': '跌破年线'
                        }
                        trades.append(trade)
                        print(f"  {current_date.strftime('%Y-%m-%d')}: 触发买入，开始定投，乖离率={current_divergence:.2f}%，计划{self.invest_days}日投完（基础金额{base_daily_amount:,.2f}）")

                        daily_record['操作'] = '开始定投'
                        daily_record['备注'] = f'乖离率{current_divergence:.2f}%，计划{self.invest_days}日（基础金额{base_daily_amount:,.2f}）'
                # else: 正在定投中，不重置（定投不重置原则）

            # === 🆕 步骤6：执行定投（含深度加倍）===
            if is_investing and not sell_triggered and remaining_days > 0:
                if cash <= 0:
                    # 资金耗尽，提前结束定投
                    is_investing = False
                    remaining_days = 0
                    base_daily_amount = 0
                    if daily_record['操作'] == '':  # 🔧 Bug K：哨兵改为空串
                        daily_record['操作'] = '定投结束(资金耗尽)'
                        daily_record['备注'] = '剩余现金耗尽，提前结束定投'
                elif cash < self.lump_sum_threshold:
                    # 🆕 剩余资金低于阈值：一次性全仓买入并结束定投周期
                    invest_amount = cash
                    # 🆕 应用交易成本
                    gross, commission, stamp_duty = self._apply_buy_costs(invest_amount)
                    buy_shares = gross / current_price
                    shares += buy_shares
                    cash = 0
                    # 🆕 累加交易成本
                    self.cumulative_commission += commission
                    self.cumulative_stamp_duty += stamp_duty
                    remaining_days_before = remaining_days
                    remaining_days = 0
                    is_investing = False
                    base_daily_amount = 0

                    trade = {
                        '日期': current_date,
                        '操作': '定投终止+全仓买入',
                        '价格': current_price,
                        '倍数': 1.0,
                        '计划金额': invest_amount,
                        '实际金额': invest_amount,
                        '份额': buy_shares,
                        '剩余天数': 0,
                        '剩余资金': 0.0,
                        '佣金': commission,  # 🆕
                        '印花税': stamp_duty,  # 🆕
                        '净投入': gross,  # 🆕
                        '触发条件': f'剩余cash({invest_amount:.2f})<阈值{self.lump_sum_threshold}，提前结束定投（原剩{remaining_days_before}日）'
                    }
                    trades.append(trade)
                    print(f"  {current_date.strftime('%Y-%m-%d')}: 定投终止+全仓买入：剩余cash={invest_amount:.2f}元 < 阈值，一次性买入{buy_shares:.4f}份（原剩{remaining_days_before}日定投终止）")

                    if daily_record['操作'] in ['开始定投', '强制重置+开始定投', '快照启动+开始定投']:
                        daily_record['操作'] = daily_record['操作']  # 保留原操作
                        daily_record['备注'] += f'；剩余资金不足，全仓买入{invest_amount:.2f}元，定投终止'
                    else:
                        daily_record['操作'] = '定投终止+全仓买入'
                        daily_record['备注'] = f'剩余cash({invest_amount:.2f})<阈值，一次性买入{buy_shares:.4f}份，定投终止'
                else:
                    # 🆕 计算当日倍数
                    multiplier = self._get_dca_multiplier(current_divergence)
                    planned_amount = base_daily_amount * multiplier
                    # 🆕 兜底：剩余资金不足时按实际现金买入
                    invest_amount = min(planned_amount, cash)
                    # 🆕 应用交易成本
                    gross, commission, stamp_duty = self._apply_buy_costs(invest_amount)
                    buy_shares = gross / current_price

                    shares += buy_shares
                    cash -= invest_amount
                    # 🆕 累加交易成本
                    self.cumulative_commission += commission
                    self.cumulative_stamp_duty += stamp_duty
                    remaining_days -= 1
                    # ⚠️ 不再重分配 base_daily_amount（关键改动！）

                    trade = {
                        '日期': current_date,
                        '操作': '定投',
                        '价格': current_price,
                        '倍数': multiplier,
                        '计划金额': planned_amount,
                        '实际金额': invest_amount,
                        '份额': buy_shares,
                        '剩余天数': remaining_days,
                        '剩余资金': cash,
                        '佣金': commission,  # 🆕
                        '印花税': stamp_duty,  # 🆕
                        '净投入': gross,  # 🆕
                    }
                    trades.append(trade)

                    # 若当天已经开始定投/强制重置/快照启动，备注追加定投信息
                    if daily_record['操作'] in ['开始定投', '强制重置+开始定投', '快照启动+开始定投']:
                        daily_record['备注'] += f'；{multiplier}×投{invest_amount:,.0f}元，买{buy_shares:.2f}份，剩{remaining_days}日'
                    else:
                        daily_record['操作'] = f'定投({multiplier}×)'
                        daily_record['备注'] = f'{multiplier}×投{invest_amount:,.0f}元（乖离率{current_divergence:.2f}%），买{buy_shares:.2f}份，剩{remaining_days}日'

                    if remaining_days == 0:
                        is_investing = False
                        base_daily_amount = 0

            # === 步骤7：同步状态到 daily_record（关键：cash/shares 可能在步骤4-6被修改）===
            position_value = shares * current_price
            total_assets = cash + position_value
            daily_record['空仓资金'] = cash
            daily_record['持仓份额'] = shares
            daily_record['持仓市值'] = position_value
            daily_record['总资产'] = total_assets
            daily_record['累计收益率'] = (total_assets - self.initial_capital) / self.initial_capital * 100
            # 🆕 同步累计交易成本（今日交易后已更新 self.cumulative_*）
            daily_record['累计佣金'] = self.cumulative_commission
            daily_record['累计印花税'] = self.cumulative_stamp_duty
            daily_record['累计交易成本'] = self.cumulative_commission + self.cumulative_stamp_duty

            # === 🔧 修复 Bug K：回填"无交易日"的持仓状态标签 ===
            # 必须放在步骤7（shares/cash 已定稿）之后：'操作' 若仍是哨兵空串，
            # 说明今日没有任何交易，此时按【实际持仓】而非固定字面量标注。
            # 旧代码一律标 '空仓'，导致满仓持有日也显示"空仓"——只影响 CSV 展示列，
            # 不参与任何计算（收益率走 '总资产'），但会严重误导人读交易记录。
            if daily_record['操作'] == '':
                if shares > 1e-9:
                    pos_pct = position_value / total_assets * 100 if total_assets > 0 else 0.0
                    if is_investing:
                        daily_record['操作'] = f'定投中持有({pos_pct:.0f}%仓)'
                    else:
                        daily_record['操作'] = f'持有({pos_pct:.0f}%仓)'
                else:
                    daily_record['操作'] = '空仓'

            # 计算当日收益率
            if i > 0:
                prev_total_assets = daily_records[-1]['总资产'] if daily_records else self.initial_capital
                daily_return = (total_assets - prev_total_assets) / prev_total_assets * 100
                daily_record['当日收益率'] = daily_return

            daily_records.append(daily_record)

        # 保存交易记录
        self.trading_records = trades

        # 将每日记录转换为DataFrame
        self.daily_df = pd.DataFrame(daily_records)

        print(f"\n回测完成！")
        print(f"  总交易次数: {len(trades)}")
        print(f"  最终总资产: {total_assets:,.2f} 元")
        print(f"  累计收益率: {(total_assets - self.initial_capital) / self.initial_capital * 100:.2f}%")

        return True

    def calculate_metrics(self):
        """计算回测指标"""
        if self.daily_df is None or len(self.daily_df) == 0:
            print("请先运行回测")
            return None

        print("\n" + "="*60)
        print("计算回测指标")
        print("="*60)

        df = self.daily_df

        # 交易日数与年化系数
        # 修复 Bug H：原硬编码 252，但本数据实际约 243 交易日/年（5001 行 /
        # 20.58 日历年），使 years 少算 3.6%、所有年化绝对值虚高约 3.7%。
        # 改为由数据本身实测：总交易日 / 总日历年数。策略与基准同向偏移，故
        # 【差值】原本基本守恒，但对外引用的绝对值全错。
        _cal_years = (df['日期'].iloc[-1] - df['日期'].iloc[0]).days / 365.25
        if _cal_years > 0:
            TRADING_DAYS_PER_YEAR = len(df) / _cal_years
        else:
            TRADING_DAYS_PER_YEAR = 243.0     # 单日等退化样本的兜底

        # ============ 策略指标 ============
        initial_price = df['收盘价'].iloc[0]
        final_price = df['收盘价'].iloc[-1]
        initial_date = df['日期'].iloc[0]
        final_date = df['日期'].iloc[-1]
        benchmark_return = (final_price - initial_price) / initial_price * 100

        strategy_return = df['累计收益率'].iloc[-1]

        # 🆕 修复年化收益计算：用 252 交易日/年
        total_days = len(df)
        years = total_days / TRADING_DAYS_PER_YEAR
        annual_return = (1 + strategy_return / 100) ** (1 / years) - 1

        # 计算最大回撤
        max_drawdown = self.calculate_max_drawdown(df['总资产'])

        # 🆕 修复年化波动率：用 √252 而非 √365
        daily_returns = df['当日收益率'].values
        annual_volatility = np.std(daily_returns) * np.sqrt(TRADING_DAYS_PER_YEAR)

        # 计算夏普比率（使用空仓收益率作为无风险利率）
        # 修复 Bug A：原为 daily_risk_free * TRADING_DAYS_PER_YEAR * 100，即把按
        # 365 日定义的日利率乘以 252 还原年利率，天数口径自相矛盾，实际生效仅
        # 0.8236% 而非设定的 1.2%（缺口 31%，252/365=0.69）。
        # cash_return_rate 本身就是年化值（见 __init__ 文档），直接使用即可，
        # 无需「年化→日→年化」这趟往返，结构上也就不可能再出现口径不匹配。
        annual_risk_free = self.cash_return_rate
        sharpe_ratio = (annual_return * 100 - annual_risk_free) / annual_volatility if annual_volatility > 0 else 0

        # 计算下行波动率（修复 Bug G：见 calculate_downside_volatility 说明）
        downside_volatility = self.calculate_downside_volatility(
            daily_returns, TRADING_DAYS_PER_YEAR)

        # 计算索提诺比率
        sortino_ratio = (annual_return * 100 - annual_risk_free) / downside_volatility if downside_volatility > 0 else 0

        # 计算卡尔马比率
        calmar_ratio = (annual_return * 100) / abs(max_drawdown) if max_drawdown != 0 else 0

        # ============ 🆕 基准指标（H20269 价格本身的指标，用于公平对比）============
        # 基准累计收益率已计算：benchmark_return

        # 基准日收益率
        benchmark_daily_returns = df['收盘价'].pct_change().dropna().values * 100

        # 基准年化收益率
        benchmark_annual_return = (final_price / initial_price) ** (1 / years) - 1

        # 基准最大回撤（基于价格序列）
        benchmark_max_drawdown = self.calculate_max_drawdown(df['收盘价'])

        # 基准年化波动率
        benchmark_annual_volatility = np.std(benchmark_daily_returns) * np.sqrt(TRADING_DAYS_PER_YEAR)

        # 基准夏普比率
        benchmark_sharpe = (benchmark_annual_return * 100 - annual_risk_free) / benchmark_annual_volatility if benchmark_annual_volatility > 0 else 0

        # 基准下行波动率与索提诺（修复 Bug G：与策略同一口径）
        benchmark_downside_vol = self.calculate_downside_volatility(
            benchmark_daily_returns, TRADING_DAYS_PER_YEAR)
        benchmark_sortino = (benchmark_annual_return * 100 - annual_risk_free) / benchmark_downside_vol if benchmark_downside_vol > 0 else 0

        # 基准卡尔马
        benchmark_calmar = (benchmark_annual_return * 100) / abs(benchmark_max_drawdown) if benchmark_max_drawdown != 0 else 0

        # ============ 🆕 同仓位静态混合基准（w 指数 + (1-w) 现金，买入持有）============
        # 为什么需要它：满仓指数基准与策略【风险暴露不对等】。策略平均仓位仅
        # avg_position_ratio，其较高的夏普中有一部分只是"没满仓"的机械结果，
        # 而非择时能力。本基准把仓位固定在与策略相同的平均水平、且【不做任何
        # 择时】（期初买入后持有到底），因此：
        #     策略 - 满仓指数  = 择时贡献 + 现金拖累（两者混在一起，无法分离）
        #     策略 - 同仓位混合 = 择时贡献（这才是策略真正的增加值）
        # 这是本项目唯一能分离"择时能力"与"低仓位副作用"的口径。
        #
        # ⚠️ 只对【收益类】指标有效。最大回撤是尾部统计量，均值匹配的基准无法
        # 评价（策略仓位双峰分布，回撤由峰值暴露而非平均暴露决定）——
        # 详见 _blended_benchmark_curve 的「适用边界」说明。回撤请对满仓指数比。
        position_ratios = df['持仓市值'] / df['总资产'] * 100
        avg_position_ratio = position_ratios.mean()
        blend_weight = avg_position_ratio / 100.0

        daily_cash_return = self.calculate_daily_return(self.cash_return_rate)
        blend_nav = self._blended_benchmark_curve(df, blend_weight, daily_cash_return)
        blend_series = pd.Series(blend_nav, index=df.index)

        blend_return = (blend_nav[-1] / blend_nav[0] - 1) * 100
        blend_annual_return = (blend_nav[-1] / blend_nav[0]) ** (1 / years) - 1
        blend_max_drawdown = self.calculate_max_drawdown(blend_series)
        blend_daily_returns = blend_series.pct_change().dropna().values * 100
        blend_annual_volatility = np.std(blend_daily_returns) * np.sqrt(TRADING_DAYS_PER_YEAR)
        blend_sharpe = (blend_annual_return * 100 - annual_risk_free) / blend_annual_volatility if blend_annual_volatility > 0 else 0
        blend_downside_vol = self.calculate_downside_volatility(
            blend_daily_returns, TRADING_DAYS_PER_YEAR)
        blend_sortino = (blend_annual_return * 100 - annual_risk_free) / blend_downside_vol if blend_downside_vol > 0 else 0
        blend_calmar = (blend_annual_return * 100) / abs(blend_max_drawdown) if blend_max_drawdown != 0 else 0

        # ============ 交易统计 ============
        total_trades = len(self.trading_records)
        buy_trades = len([t for t in self.trading_records if t['操作'] in ['定投', '开始定投', '强制重置+开始定投', '快照启动+开始定投']])
        sell_trades = len([t for t in self.trading_records if t['操作'] in ['卖出50%', '清仓', '清仓(跳过a%)']])
        # 🆕 全仓买入统计（小资金场景）
        lump_sum_trades = len([t for t in self.trading_records
                               if '全仓买入' in str(t.get('操作', ''))])

        # 资金使用率（修复：使用每日比例的均值，而非均值之比）
        # 注：position_ratios / avg_position_ratio 已在同仓位混合基准处算出，
        # 此处不再重复计算（该值同时用作混合基准的权重 w）。

        # 🆕 深度定投倍数统计
        multiplier_counts = {1.0: 0, 2.0: 0, 3.0: 0, '其他': 0}
        for t in self.trading_records:
            if t['操作'] == '定投':
                mult = t.get('倍数', 1.0)
                if mult in multiplier_counts:
                    multiplier_counts[mult] += 1
                else:
                    multiplier_counts['其他'] += 1

        # 🆕 交易成本统计（从 trading_records 汇总）
        total_commission = sum(t.get('佣金', 0) for t in self.trading_records)
        total_stamp_duty = sum(t.get('印花税', 0) for t in self.trading_records)
        total_trading_cost = total_commission + total_stamp_duty
        # 仅统计含费用的交易笔数（排除"开始定投"等纯信号记录）
        cost_bearing_trades = sum(1 for t in self.trading_records if '佣金' in t)

        # 🆕 实际佣金率（最低佣金效应）—— 如实披露，非建模误差
        # n=40 的分批定投使单笔金额过小，绝大多数笔数被 min_commission 兜底，
        # 使实际费率远高于名义值（实测 0.088%，为名义 0.025% 的 3.5 倍）。
        _fee_recs = [t for t in self.trading_records if '佣金' in t]
        _at_floor = sum(1 for t in _fee_recs
                        if abs(t['佣金'] - self.min_commission) < 1e-9)
        _turnover = sum(t.get('净投入', t.get('金额', 0)) for t in _fee_recs)
        if _fee_recs and _turnover > 0:
            actual_commission_rate = total_commission / _turnover * 100
            at_floor_pct = _at_floor / len(_fee_recs) * 100
        else:
            actual_commission_rate = None
            at_floor_pct = 0.0

        metrics = {
            '初始资金': self.initial_capital,
            '最终资产': df['总资产'].iloc[-1],
            '回测天数': total_days,
            '回测年数': years,
            # 🆕 起止日期与价格（明确标注基准锚点）
            '起始日期': initial_date,
            '结束日期': final_date,
            '起始价格(基准0%锚点)': initial_price,
            '结束价格': final_price,
            # 策略指标
            '策略累计收益率': strategy_return,
            '策略年化收益率': annual_return * 100,
            '策略最大回撤': max_drawdown,
            '策略年化波动率': annual_volatility,
            '策略夏普比率': sharpe_ratio,
            '策略索提诺比率': sortino_ratio,
            '策略卡尔马比率': calmar_ratio,
            # 基准指标（🆕 补全）
            '基准累计收益率': benchmark_return,
            '基准年化收益率': benchmark_annual_return * 100,
            '基准最大回撤': benchmark_max_drawdown,
            '基准年化波动率': benchmark_annual_volatility,
            '基准夏普比率': benchmark_sharpe,
            '基准索提诺比率': benchmark_sortino,
            '基准卡尔马比率': benchmark_calmar,
            # 🆕 同仓位静态混合基准（风险暴露与策略对等的对照组）
            '混合基准权重%': blend_weight * 100,
            '混合基准累计收益率': blend_return,
            '混合基准年化收益率': blend_annual_return * 100,
            '混合基准最大回撤': blend_max_drawdown,
            '混合基准年化波动率': blend_annual_volatility,
            '混合基准夏普比率': blend_sharpe,
            '混合基准索提诺比率': blend_sortino,
            '混合基准卡尔马比率': blend_calmar,
            # 对比指标
            '超额收益(累计)': strategy_return - benchmark_return,
            '超额收益(年化)': annual_return * 100 - benchmark_annual_return * 100,
            '夏普差': sharpe_ratio - benchmark_sharpe,
            '回撤差(策略-基准)': max_drawdown - benchmark_max_drawdown,
            # 🆕 相对同仓位混合基准的超额（= 择时贡献，已剔除低仓位副作用）
            '择时超额(累计)': strategy_return - blend_return,
            '择时超额(年化)': annual_return * 100 - blend_annual_return * 100,
            '择时夏普差': sharpe_ratio - blend_sharpe,
            # ⚠️ 下面这项【不可作为"控回撤能力"的证据】：均值匹配基准只对收益类
            # 指标成立，最大回撤是尾部统计量。保留仅为完整性与历史可比。
            '择时回撤差(策略-混合)': max_drawdown - blend_max_drawdown,
            # 交易统计
            '交易次数': total_trades,
            '买入次数': buy_trades,
            '卖出次数': sell_trades,
            '🆕全仓买入次数': lump_sum_trades,
            '平均资金使用率': avg_position_ratio,
            # 深度定投统计
            '1×定投次数': multiplier_counts[1.0],
            '2×定投次数': multiplier_counts[2.0],
            '3×定投次数': multiplier_counts[3.0],
            '其他倍数定投次数': multiplier_counts['其他'],
            # 🆕 交易成本统计
            '总佣金': total_commission,
            '总印花税': total_stamp_duty,
            '总交易成本': total_trading_cost,
            '含费用交易笔数': cost_bearing_trades,
            # 🆕 实际佣金率披露（最低佣金效应）
            '实际佣金率%': actual_commission_rate,
            '触发最低佣金笔数': _at_floor,
            '触发最低佣金占比%': at_floor_pct,
            '印花税免征': self.stamp_duty_exempt,
            '佣金占初始资金比例': total_commission / self.initial_capital * 100,
            '总成本占初始资金比例': total_trading_cost / self.initial_capital * 100,
            '总成本占最绔回报比例': (total_trading_cost / (df['总资产'].iloc[-1] - self.initial_capital) * 100)
                                 if df['总资产'].iloc[-1] > self.initial_capital else float('inf'),
        }

        # 打印指标（🆕 重新设计输出，分基础信息/策略/基准/对比四部分）
        print(f"\n{'='*60}")
        print(f"=== 基础信息（含起止日期与基准锚点） ===")
        print(f"{'='*60}")
        print(f"起始日期: {metrics['起始日期'].strftime('%Y-%m-%d')}（基准 0% 锚点）")
        print(f"结束日期: {metrics['结束日期'].strftime('%Y-%m-%d')}")
        print(f"起始价格: {metrics['起始价格(基准0%锚点)']:,.3f}（基准累计收益率以此为 0%）")
        print(f"结束价格: {metrics['结束价格']:,.3f}")
        print(f"初始资金: {metrics['初始资金']:,.0f} 元")
        print(f"最终资产: {metrics['最终资产']:,.0f} 元")
        print(f"回测天数: {metrics['回测天数']} 个交易日（约 {metrics['回测年数']:.2f} 年）")

        print(f"\n{'='*60}")
        print(f"=== 策略 vs 基准 对比（核心） ===")
        print(f"{'='*60}")
        print(f"{'指标':<20}{'策略':>15}{'基准':>15}{'差值':>15}")
        print(f"{'-'*65}")
        print(f"{'累计收益率(%)':<20}{metrics['策略累计收益率']:>15.2f}{metrics['基准累计收益率']:>15.2f}{metrics['超额收益(累计)']:>15.2f}")
        print(f"{'年化收益率(%)':<20}{metrics['策略年化收益率']:>15.2f}{metrics['基准年化收益率']:>15.2f}{metrics['超额收益(年化)']:>15.2f}")
        print(f"{'最大回撤(%)':<20}{metrics['策略最大回撤']:>15.2f}{metrics['基准最大回撤']:>15.2f}{metrics['回撤差(策略-基准)']:>15.2f}")
        print(f"{'年化波动率(%)':<20}{metrics['策略年化波动率']:>15.2f}{metrics['基准年化波动率']:>15.2f}{metrics['策略年化波动率']-metrics['基准年化波动率']:>15.2f}")
        print(f"{'夏普比率':<20}{metrics['策略夏普比率']:>15.2f}{metrics['基准夏普比率']:>15.2f}{metrics['夏普差']:>15.2f}")
        print(f"{'索提诺比率':<20}{metrics['策略索提诺比率']:>15.2f}{metrics['基准索提诺比率']:>15.2f}{metrics['策略索提诺比率']-metrics['基准索提诺比率']:>15.2f}")
        print(f"{'卡尔马比率':<20}{metrics['策略卡尔马比率']:>15.2f}{metrics['基准卡尔马比率']:>15.2f}{metrics['策略卡尔马比率']-metrics['基准卡尔马比率']:>15.2f}")

        print(f"\n{'='*60}")
        print(f"=== 交易统计 ===")
        print(f"{'='*60}")
        print(f"总交易次数: {metrics['交易次数']}")
        print(f"  买入次数（定投类）: {metrics['买入次数']}")
        print(f"  🆕 全仓买入次数（小资金场景）: {metrics['🆕全仓买入次数']}")
        print(f"  卖出次数: {metrics['卖出次数']}")
        print(f"平均资金使用率: {metrics['平均资金使用率']:.2f}%")
        if self.dca_tiers:
            print(f"\n🆕 深度定投倍数分布:")
            print(f"  1× 定投次数: {metrics['1×定投次数']}")
            print(f"  2× 定投次数: {metrics['2×定投次数']}")
            print(f"  3× 定投次数: {metrics['3×定投次数']}")
            if metrics['其他倍数定投次数'] > 0:
                print(f"  其他倍数定投次数: {metrics['其他倍数定投次数']}")

        return metrics

    def calculate_max_drawdown(self, total_assets_series):
        """
        计算最大回撤

        参数：
        total_assets_series: 总资产序列

        返回：
        最大回撤（百分比）
        """
        # 计算累计最高点
        cummax = total_assets_series.cummax()

        # 计算回撤
        drawdown = (total_assets_series - cummax) / cummax * 100

        # 最大回撤
        max_drawdown = drawdown.min()

        return max_drawdown

    @staticmethod
    def calculate_downside_volatility(daily_returns_pct, trading_days_per_year):
        """计算年化下行波动率（Sortino 分母）

        修复 Bug G：原为 np.std(负收益) * sqrt(TD)，有两处偏差 ——
          1) np.std 度量的是负收益【相对其自身均值】的离散度，而下行风险应度量
             【相对 0（或 MAR）】的偏离；
          2) 只除以下跌天数，而非全部天数。
        正确定义为 target downside deviation：sqrt(mean(min(r,0)^2))，对全部
        交易日取均值（上涨日贡献 0）。
        原写法使分母虚大，且因策略下跌天数远少于基准（低仓位）而【偏误不对称】，
        实测低估了策略的索提诺（分母 10.7664 vs 正确 9.2235）。
        """
        r = np.asarray(daily_returns_pct, dtype=float)
        if r.size == 0:
            return 0.0
        downside = np.minimum(r, 0.0)
        return float(np.sqrt(np.mean(downside ** 2)) * np.sqrt(trading_days_per_year))

    def _blended_benchmark_curve(self, df, weight, daily_cash_return):
        """构造【同仓位静态混合基准】的净值曲线（买入持有口径）

        起始日一次性买入 w 份指数 + (1-w) 份现金，此后【不做任何交易】，
        仅现金按日历日计息、股票部分随指数自由漂移。这是 Henriksson–Merton
        (1981) 择时检验里的 buy-and-hold 对照组。

        为什么是买入持有而不是每日再平衡：
          ① 每日再平衡需要 2571 次交易（2016 组实测累计换手达 4 倍总资产），
             而本基准【不扣交易成本】，等于白送策略比不到的便宜；
          ② 买入持有实盘真的可执行（零交易），对照才公平；
          ③ 再平衡本身是一种「高抛低吸」择时动作，会把择时收益混进"基准"里，
             与本基准「不做任何择时」的定位自相矛盾。
        实测两种口径结论方向一致（策略回撤仍 17/21 组更差），但再平衡口径
        把差距夸大了：均值 -1.52pp vs 买入持有 -0.90pp。

        ⚠️ w 的性质：w = 策略【事后】实测的日均仓位（见调用处 avg_position_ratio）。
        起始日无法预知该取多少仓位，故本基准【不是一个可投资的替代方案】，
        而是一个【归因工具】—— 用来把「策略 - 满仓指数」拆成择时贡献与现金拖累。

        ⚠️ 适用边界（重要）：均值匹配只对【线性/平均型】统计量成立，即累计收益、
        年化收益可以这样比。**最大回撤是尾部统计量，不能用本基准评价** ——
        策略仓位是双峰分布（2016 组实测 45.4% 的交易日仓位 >95%、7.3% 为空仓，
        中位数 63% 与均值 70% 相差甚远），回撤由回撤窗口内的【峰值暴露】决定，
        而本基准全程只有 w 的暴露。拿两者比最大回撤，测的是仓位分布形状，
        不是择时能力。回撤对比请用满仓指数基准（实测策略 21/21 组均不劣于满仓）。
        """
        price = df['收盘价'].values
        dates = df['日期'].values
        nav = np.empty(len(price), dtype=float)
        nav[0] = 1.0
        # 期初建仓：w 份买指数（折算成份额后不再变动），(1-w) 份留现金
        shares = weight / price[0]
        cash = 1.0 - weight
        for i in range(1, len(price)):
            elapsed = (dates[i] - dates[i - 1]) / np.timedelta64(1, 'D')
            cash *= (1 + daily_cash_return) ** float(elapsed)
            nav[i] = shares * price[i] + cash
        return nav

    def save_results(self, output_dir='output/backtests/h20269/_default'):
        """保存回测结果"""
        if self.daily_df is None:
            print("请先运行回测")
            return

        # 创建输出目录
        os.makedirs(output_dir, exist_ok=True)

        print(f"\n保存回测结果到: {output_dir}")

        # 1. 保存每日记录
        daily_file = os.path.join(output_dir, f'{self.stock_name}_滚动仓位每日记录.csv')
        self.daily_df.to_csv(daily_file, index=False, encoding='utf-8-sig')
        print(f"  每日记录: {daily_file}")

        # 2. 保存交易记录
        trades_file = os.path.join(output_dir, f'{self.stock_name}_滚动仓位交易记录.csv')
        trades_df = pd.DataFrame(self.trading_records)
        trades_df.to_csv(trades_file, index=False, encoding='utf-8-sig')
        print(f"  交易记录: {trades_file}")

        # ============================================================
        # 3. 指标统计 / 收益率对比图 —— 已下线（2026-08-23）
        # ------------------------------------------------------------
        # 原先此处还写两份产物，均已并入「时间维度分析」：
        #   ① {stock}_滚动仓位回测指标.txt
        #      -> 全部内容并入 时间维度分析报告.md（第 1 节总体表现表 +
        #         第 6 节策略参数 + 第 7 节交易与成本统计），带锚点目录，
        #         不必再在两个文件之间来回翻。
        #   ② {stock}_滚动仓位收益率对比.html（4 子图）
        #      -> 与 时间维度分析_综合可视化.html 高度重复（子图①收益率对比、
        #         子图②价格vsMA250、子图④持仓比例三者完全同源），后者更全
        #         （多出相对收益曲线与买卖时点标注），故只保留后者。
        #         「价格 vs MA250」已合并进后者子图①的次坐标轴。
        # 指标本身仍由 calculate_metrics() 提供，供 PerformanceAnalyzer 与
        # build_cross_group_report.py 取用 —— 只是不再单独落盘。
        # ============================================================

        print(f"\n所有结果已保存！")

    def run(self, output_dir='output/backtests/h20269/_default'):
        """运行完整回测流程"""
        # 1. 加载数据
        if not self.load_data():
            return False

        # 2. 运行回测
        if not self.run_backtest():
            return False

        # 3. 计算指标
        metrics = self.calculate_metrics()

        # 4. 保存结果
        self.save_results(output_dir)

        return True


# ============ 主程序 ============
if __name__ == '__main__':
    # 默认参数（含 🆕 起止日期 与 🆕 深度定投档位）
    backtest = RollingPositionBacktest(
        csv_file_path='data/H20269历史数据.csv',
        invest_days=40,  # n: 定投交易日数
        sell_threshold_a=15.0,  # a: 第一卖出阈值
        sell_threshold_b=17.5,  # b: 第二卖出阈值
        cash_return_rate=1.2,  # c: 空仓年化收益率
        initial_capital=100000,  # 初始资金10万

        # 🆕 起止日期（None=数据首日/末日；可传 'YYYY-MM-DD' 字符串）
        start_date=None,  # 例: '2020-01-01'
        end_date=None,    # 例: '2024-12-31'

        # 🆕 深度定投档位：[(threshold, multiplier), ...]
        # 默认 [(-8.0, 3.0), (-4.0, 2.0)]
        #   ≤-8%: 3×, -8%~-4%: 2×, 其他: 1×
        # 传入 [] 关闭深度定投（回退到原策略全1×）
        dca_tiers=None,  # 使用默认三档加倍
    )

    # 运行回测
    backtest.run()
