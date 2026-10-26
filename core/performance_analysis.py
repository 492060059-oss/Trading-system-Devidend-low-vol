# -*- coding: utf-8 -*-
"""
策略表现时间维度分析
- 按市场阶段切分，分析策略在每个阶段的超额收益
- 识别关键买卖时点
- 生成综合可视化HTML与markdown报告
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
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# Windows 控制台 UTF-8 输出
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass


# ============================================================
# 市场阶段定义（基于A股2015-2026关键事件）
# 阶段划分依据：重大政策/事件 + 趋势转折点
#
# 这 9 段是【同一次回测】的时间轴切片（收益归因），不是 9 个独立起始日回测；
# 起始日验证是另一套东西，见 run_multiple_backtests.py CONFIGS。
# 因此各段必须首尾相接、不重叠、且【完整覆盖回测的全部交易日】——
# 否则各段收益连乘无法还原总收益（见 analyze_phases 末尾的覆盖率断言）。
#
# 修复 Bug F：首段 start / 末段 end 设为 None 表示【向数据边界敞开】。
# 原先写死 '2015-05-04' 与 '2026-07-20'，导致两头的交易日不属于任何阶段被
# 静默丢弃：实测 2014-07-08 起那组漏掉开头 199 天（指数 +104.87% 而策略全程
# 空仓仅 +0.65%），基准连乘还原误差高达 -209.43 pp；2026-05 起那组漏掉末尾
# 11 天（占该组 17.5%）。末段敞开后，数据更新时尾部自动跟随，无需再改常量。
# ============================================================
MARKET_PHASES = [
    {
        'name': '牛市顶部→股灾期',
        # start=None：向前敞开到数据起点。对 2015-05 之后开始的回测无影响；
        # 对更早开始的回测，会把 2015-05-04 前的行情并入本段。
        'start': None, 'end': '2015-09-30',
        'event': '2015-06-15 5178点大顶→股灾1.0/2.0',
        'description': '指数见顶后快速下跌，期间多次千股跌停'
    },
    {
        'name': '股灾后→熔断期',
        'start': '2015-10-01', 'end': '2016-06-30',
        'event': '2016-01-04 熔断机制启动，2638点大底',
        'description': '熔断引发二次暴跌，随后震荡磨底'
    },
    {
        'name': '蓝筹慢牛期',
        'start': '2016-07-01', 'end': '2017-12-31',
        'event': '白马股行情（茅台翻倍）',
        'description': '价值投资兴起，沪深300领涨'
    },
    {
        'name': '贸易战熊市',
        'start': '2018-01-01', 'end': '2019-01-31',
        'event': '2018-03-23 贸易战开始，全年单边下跌',
        'description': '上证从3587跌至2440，跌幅32%'
    },
    {
        'name': '牛熊切换→疫情底',
        'start': '2019-02-01', 'end': '2020-03-31',
        'event': '2019春季躁动 + 2020-03 全球疫情冲击',
        'description': '科技股牛市启动，疫情打断后快速修复'
    },
    {
        'name': '放水牛市',
        'start': '2020-04-01', 'end': '2021-02-28',
        'event': '茅指数见顶（核心资产顶）',
        'description': '央行放水，核心资产泡沫化'
    },
    {
        'name': '风格切换→红利启动',
        'start': '2021-03-01', 'end': '2022-04-30',
        'event': '茅指数崩盘+红利低波切换+俄乌冲突',
        'description': '核心资产估值回归，红利风格开始占优'
    },
    {
        'name': '红利低波主升浪',
        'start': '2022-05-01', 'end': '2024-09-23',
        'event': '中特估+红利低波持续跑赢',
        'description': '红利低波成为最强主线，稳步创新高'
    },
    {
        'name': '924行情→加速上涨',
        # end=None：向后敞开到数据终点，数据更新后尾部自动跟随，不必再改此常量。
        'start': '2024-09-24', 'end': None,
        'event': '2024-9-24 央行放水，指数快速突破',
        'description': '政策驱动+全球宽松，红利低波加速'
    },
]


class PerformanceAnalyzer:
    """策略表现时间维度分析器"""

    def __init__(self, daily_records_csv, metrics=None, backtest=None):
        """
        参数：
        daily_records_csv: rolling_position_backtest 输出的每日记录CSV
        metrics: 可选，RollingPositionBacktest.calculate_metrics() 的返回字典。
                 传入后报告会多出【总体表现三方对照表】（策略/满仓基准/静态混合）
                 与交易成本统计 —— 这些数原先落在独立的
                 {stock}_滚动仓位回测指标.txt，2026-08-23 起并入本报告。
        backtest: 可选，RollingPositionBacktest 实例，仅用于读取策略参数
                  （n / a / b / c / 深度定投档位 / 费率）写进报告末尾。

        两者都不传时本类退化为纯 CSV 模式（老行为）：报告仍可生成，
        只是缺少「静态混合基准」「策略参数」「交易成本」三块 —— 会在报告里
        显式写明缺失原因，而不是静默省略。
        """
        self.df = pd.read_csv(daily_records_csv)
        self.df['日期'] = pd.to_datetime(self.df['日期'])
        self.metrics = metrics
        self.bt = backtest
        self._prepare_data()

    # ------------------------------------------------------------------
    # 便捷构造：从回测参数直接【在内存里重跑】一遍，拿到 metrics + 参数
    # ------------------------------------------------------------------
    @classmethod
    def from_backtest(cls, daily_records_csv, backtest):
        """用一个【已经跑完】的 RollingPositionBacktest 实例构造分析器"""
        return cls(daily_records_csv, metrics=backtest.calculate_metrics(),
                   backtest=backtest)

    def _prepare_data(self):
        """计算基准累计收益、相对收益、持仓比例、日收益率"""
        initial_price = self.df['收盘价'].iloc[0]
        # 基准累计收益 = 以起始价为0%锚点
        self.df['基准累计收益%'] = (self.df['收盘价'] - initial_price) / initial_price * 100
        # 相对收益 = 策略累计 - 基准累计
        self.df['相对收益%'] = self.df['累计收益率'] - self.df['基准累计收益%']
        # 持仓比例
        self.df['持仓比例%'] = self.df['持仓市值'] / self.df['总资产'] * 100
        # 日收益率（用于滚动指标）
        self.df['策略日收益%'] = self.df['总资产'].pct_change() * 100
        self.df['基准日收益%'] = self.df['收盘价'].pct_change() * 100

    @staticmethod
    def _max_drawdown(series):
        """计算序列最大回撤（百分比）"""
        cummax = series.cummax()
        drawdown = (series - cummax) / cummax * 100
        return drawdown.min() if len(drawdown) > 0 else 0

    def analyze_phases(self):
        """按市场阶段切分，计算每段的策略/基准/超额收益与回撤

        各段必须完整覆盖全部交易日（见末尾断言），否则收益归因无法自洽。
        """
        results = []
        covered = pd.Series(False, index=self.df.index)
        for phase in MARKET_PHASES:
            # 修复 Bug F：start/end 为 None 表示向该侧数据边界敞开（不设限）。
            mask = pd.Series(True, index=self.df.index)
            if phase['start'] is not None:
                mask &= self.df['日期'] >= phase['start']
            if phase['end'] is not None:
                mask &= self.df['日期'] <= phase['end']
            covered |= mask
            seg = self.df[mask]
            if len(seg) == 0:
                continue

            # 阶段自身收益率（分母为该阶段起点，策略与基准同口径，可直接相减比较）
            # 修复 Bug E：原用「累计收益率末值-首值」，两侧分母分别固定为初始资金与首日
            # 价格，各自被不同倍数放大后相减，会导致超额收益符号翻转（实测 3/9 阶段翻转）。
            # 基点取该阶段【前一交易日】收盘，使各阶段无缝衔接、连乘可精确还原总收益；
            # 首阶段无前值时退化为自身首日（此时资产=初始资金、价格=首日价格，语义正确）。
            base_i = self.df.index.get_loc(seg.index[0])
            base_i = base_i - 1 if base_i > 0 else base_i
            strategy_base = self.df['总资产'].iloc[base_i]
            benchmark_base = self.df['收盘价'].iloc[base_i]

            strategy_phase_return = (seg['总资产'].iloc[-1] / strategy_base - 1) * 100
            benchmark_phase_return = (seg['收盘价'].iloc[-1] / benchmark_base - 1) * 100
            excess = strategy_phase_return - benchmark_phase_return

            # 阶段内最大回撤
            strategy_max_dd = self._max_drawdown(seg['总资产'])
            benchmark_max_dd = self._max_drawdown(seg['收盘价'])

            # 仓位中位数（策略在这一段的平均暴露）
            median_position = seg['持仓比例%'].median()

            # 操作次数
            buy_ops = (seg['操作'].isin(['开始定投', '强制重置+开始定投', '快照启动+开始定投'])).sum()
            sell_ops = (seg['操作'].isin(['卖出50%', '清仓', '清仓(跳过a%)'])).sum()

            # 阶段起点/终点的相对收益
            rel_start = seg['相对收益%'].iloc[0]
            rel_end = seg['相对收益%'].iloc[-1]
            rel_change = rel_end - rel_start

            results.append({
                '阶段': phase['name'],
                '关键事件': phase['event'],
                '时间段': f"{seg['日期'].iloc[0].strftime('%Y-%m-%d')} ~ {seg['日期'].iloc[-1].strftime('%Y-%m-%d')}",
                '交易日数': len(seg),
                '策略阶段收益%': round(strategy_phase_return, 2),
                '基准阶段收益%': round(benchmark_phase_return, 2),
                '超额阶段收益%': round(excess, 2),
                '策略最大回撤%': round(strategy_max_dd, 2),
                '基准最大回撤%': round(benchmark_max_dd, 2),
                '仓位中位数%': round(median_position, 1),
                '买入操作': int(buy_ops),
                '卖出操作': int(sell_ops),
                '阶段起始相对收益%': round(rel_start, 2),
                '阶段结束相对收益%': round(rel_end, 2),
                '相对收益变化%': round(rel_change, 2),
            })

        # 覆盖率断言（Bug F 的守门人）：阶段划分若漏掉任何交易日，收益归因就
        # 不自洽（各段连乘无法还原总收益），且以往是【静默】发生的。宁可炸掉
        # 也不能让残缺的表悄悄流入报告。
        n_missing = int((~covered).sum())
        if n_missing:
            miss = self.df.loc[~covered, '日期']
            raise ValueError(
                f'MARKET_PHASES 未覆盖 {n_missing} 个交易日'
                f'（{miss.iloc[0].strftime("%Y-%m-%d")} ~ {miss.iloc[-1].strftime("%Y-%m-%d")}）。'
                f'数据范围 {self.df["日期"].iloc[0].strftime("%Y-%m-%d")} ~ '
                f'{self.df["日期"].iloc[-1].strftime("%Y-%m-%d")}。'
                '请调整阶段定义使其完整覆盖，或将首段 start / 末段 end 设为 None 向数据边界敞开。'
            )

        return pd.DataFrame(results)

    def identify_key_events(self):
        """识别关键操作事件（买入/卖出/强制重置时点）"""
        events = []
        for _, row in self.df.iterrows():
            op = str(row['操作'])
            if op in ['开始定投', '强制重置+开始定投', '快照启动+开始定投']:
                events.append({
                    '日期': row['日期'].strftime('%Y-%m-%d'),
                    '类型': '开始定投' if op == '开始定投' else ('强制重置' if '强制' in op else '快照启动'),
                    '方向': '买入',
                    '乖离率%': round(row['乖离率'], 2),
                    '策略累计%': round(row['累计收益率'], 2),
                    '基准累计%': round(row['基准累计收益%'], 2),
                    '相对收益%': round(row['相对收益%'], 2),
                })
            elif op == '卖出50%':
                events.append({
                    '日期': row['日期'].strftime('%Y-%m-%d'),
                    '类型': '卖出50%',
                    '方向': '卖出',
                    '乖离率%': round(row['乖离率'], 2),
                    '策略累计%': round(row['累计收益率'], 2),
                    '基准累计%': round(row['基准累计收益%'], 2),
                    '相对收益%': round(row['相对收益%'], 2),
                })
            elif op in ['清仓', '清仓(跳过a%)']:
                events.append({
                    '日期': row['日期'].strftime('%Y-%m-%d'),
                    '类型': '清仓',
                    '方向': '卖出',
                    '乖离率%': round(row['乖离率'], 2),
                    '策略累计%': round(row['累计收益率'], 2),
                    '基准累计%': round(row['基准累计收益%'], 2),
                    '相对收益%': round(row['相对收益%'], 2),
                })
        return pd.DataFrame(events)

    def compute_rolling_metrics(self, window=252):
        """计算滚动252日指标（年化收益、波动率、夏普）"""
        df = self.df.copy()
        # 滚动累计收益率（这一段的总收益）
        df['滚动252日策略收益%'] = (1 + df['策略日收益%']/100).rolling(window).apply(
            lambda x: (x.prod() - 1) * 100, raw=True)
        df['滚动252日基准收益%'] = (1 + df['基准日收益%']/100).rolling(window).apply(
            lambda x: (x.prod() - 1) * 100, raw=True)
        df['滚动252日超额%'] = df['滚动252日策略收益%'] - df['滚动252日基准收益%']

        # 滚动年化波动率
        df['滚动252日策略波动%'] = df['策略日收益%'].rolling(window).std() * np.sqrt(252)
        df['滚动252日基准波动%'] = df['基准日收益%'].rolling(window).std() * np.sqrt(252)
        return df

    # ==================================================================
    # 总体表现三方对照（策略 / 满仓基准 / 静态混合）
    # ------------------------------------------------------------------
    # 2026-08-23 新增。此前本报告只字未提静态混合基准，读者无从判断策略的
    # 超额到底来自【择时】还是仅仅来自【没满仓】。
    # ==================================================================

    # (显示名, metrics 键前缀后缀, 越大越好?, 单位)
    _OVERALL_SPEC = [
        ('年化收益率', '年化收益率', True,  '%'),
        ('总收益率',   '累计收益率', True,  '%'),
        ('年化波动率', '年化波动率', False, '%'),
        ('最大回撤',   '最大回撤',   True,  '%'),   # 负数，越接近 0 越好 → 越大越好
        ('夏普比率',   '夏普比率',   True,  ''),
        ('索提诺比率', '索提诺比率', True,  ''),
    ]

    def _csv_fallback_metrics(self, risk_free=1.2):
        """没有 metrics 时，从每日记录 CSV 自行计算策略/基准指标

        口径与 rolling_position_backtest.calculate_metrics 保持一致：
        年化天数由数据实测（Bug H），索提诺分母用 target downside
        deviation（Bug G）。**算不出静态混合基准**（它需要 cash_return_rate
        与逐日现金计息口径），故该列留空并在报告中说明原因。
        """
        df = self.df
        cal_years = (df['日期'].iloc[-1] - df['日期'].iloc[0]).days / 365.25
        tdpy = len(df) / cal_years if cal_years > 0 else 243.0
        years = len(df) / tdpy

        def _mdd(s):
            cm = s.cummax()
            return ((s - cm) / cm * 100).min()

        def _pack(cum_ret_pct, daily_pct, level_series):
            ann = ((1 + cum_ret_pct / 100) ** (1 / years) - 1) * 100
            vol = float(np.std(daily_pct) * np.sqrt(tdpy))
            downside = np.minimum(np.asarray(daily_pct, dtype=float), 0.0)
            dvol = float(np.sqrt(np.mean(downside ** 2)) * np.sqrt(tdpy))
            return {
                '年化收益率': ann,
                '累计收益率': cum_ret_pct,
                '年化波动率': vol,
                '最大回撤': _mdd(level_series),
                '夏普比率': (ann - risk_free) / vol if vol > 0 else 0.0,
                '索提诺比率': (ann - risk_free) / dvol if dvol > 0 else 0.0,
            }

        strat = _pack(df['累计收益率'].iloc[-1],
                      df['总资产'].pct_change().dropna().values * 100,
                      df['总资产'])
        bench = _pack(df['基准累计收益%'].iloc[-1],
                      df['收盘价'].pct_change().dropna().values * 100,
                      df['收盘价'])
        return strat, bench

    def overall_table(self):
        """返回 (列名列表, {行名: [值...]}, 差值行 dict, 说明文字)

        行：策略 / 满仓基准 / 静态混合(w%)；差值行：vs满仓、vs混合。
        差值统一为【策略 - 对照】，并按各指标方向判定优劣。
        """
        m = self.metrics
        cols = [c[0] for c in self._OVERALL_SPEC]

        if m is not None:
            strat = {k: m['策略' + k] for _, k, _, _ in self._OVERALL_SPEC}
            bench = {k: m['基准' + k] for _, k, _, _ in self._OVERALL_SPEC}
            blend = {k: m['混合基准' + k] for _, k, _, _ in self._OVERALL_SPEC}
            blend_w = m['混合基准权重%']
            note = None
        else:
            strat, bench = self._csv_fallback_metrics()
            blend, blend_w = None, None
            note = ('本次分析仅由每日记录 CSV 构造，未接入回测器指标，因此'
                    '**缺少静态混合基准**（它需要 cash_return_rate 与逐日现金'
                    '计息口径）。如需完整三方对照，请通过 '
                    '`PerformanceAnalyzer.from_backtest(csv, bt)` 构造，'
                    '或直接运行 scripts/backtest/run_*_backtests.py。')

        rows = {'策略': strat, '满仓基准': bench}
        if blend is not None:
            rows[f'静态混合({blend_w:.1f}%仓)'] = blend

        diffs = {}
        for label, comp in (('vs 满仓基准', bench), ('vs 静态混合', blend)):
            if comp is None:
                continue
            d = []
            for _, key, higher_better, _u in self._OVERALL_SPEC:
                delta = strat[key] - comp[key]
                better = (delta > 0) if higher_better else (delta < 0)
                d.append((delta, better))
            diffs[label] = d
        return cols, rows, diffs, note, blend_w

    def plot_analysis(self, save_path):
        """生成综合可视化 HTML

        2026-08-23 重构，改动如下（均为可读性问题，非计算口径变更）：
          · 子图从 6 个减到 3 个：删除「滚动252日收益」「滚动252日波动率」
            两图 —— 它们是同一条曲线的窗口平滑，结论与子图①③重复；
          · 原子图②「基准价格 vs MA250」并入子图①的【次坐标轴】：同一张图上
            既看累计收益、又看点位与年线，鼠标悬停一次读全四个数；
          · 删除全部阶段背景色条（add_vrect）。那套深浅竖条原是为「标注跌破
            年线起始日」设计的，搬到这里只是九段固定日历切分，与曲线无关，
            纯属视觉噪声；
          · 买卖标注由三角形改为【箭头】，买入红、卖出绿（A 股习惯）；
          · 标题与图例不再挤在顶部：图例移到图底，标题独占顶部留白；
          · 顶部新增【总体表现】表格 + 分组柱状图，不看曲线也能判断优劣。
        """
        df = self.df
        events_df = self.identify_key_events()
        has_ma250 = 'MA250' in df.columns and pd.notna(df['MA250'].iloc[0])

        COLOR_STRATEGY = '#00008B'   # 深蓝
        COLOR_BENCHMARK = '#DC143C'  # 深红
        COLOR_BLEND = '#8A2BE2'      # 紫（静态混合）
        COLOR_RELATIVE = '#006400'   # 深绿
        COLOR_PRICE = '#B0B0B0'      # 灰（次坐标轴，弱化）
        COLOR_MA250 = '#FF8C00'      # 橙（次坐标轴）
        COLOR_BUY = '#D62728'        # 红 = 买入（A 股习惯）
        COLOR_SELL = '#2CA02C'       # 绿 = 卖出

        start_str = df['日期'].iloc[0].strftime('%Y-%m-%d')
        end_str = df['日期'].iloc[-1].strftime('%Y-%m-%d')

        # ============ 图 A：总体表现（表格 + 分组柱状图）============
        fig_a = self._build_summary_figure(
            COLOR_STRATEGY, COLOR_BENCHMARK, COLOR_BLEND)

        # ============ 图 B：时间维度三子图 ============
        fig = make_subplots(
            rows=3, cols=1,
            shared_xaxes=True,
            vertical_spacing=0.06,
            row_heights=[0.52, 0.24, 0.24],
            specs=[[{'secondary_y': True}], [{}], [{}]],
            subplot_titles=(
                '① 累计收益率对比（含买卖时点；右轴为指数点位与 MA250 年线）',
                '② 相对收益曲线（策略 − 基准，>0 表示策略跑赢）',
                '③ 持仓比例',
            )
        )

        # ---- 子图①主轴：累计收益率 ----
        fig.add_trace(go.Scatter(
            x=df['日期'], y=df['累计收益率'],
            name='策略累计收益%',
            line=dict(color=COLOR_STRATEGY, width=2),
            hovertemplate='策略累计: %{y:.2f}%<extra></extra>'
        ), row=1, col=1, secondary_y=False)
        fig.add_trace(go.Scatter(
            x=df['日期'], y=df['基准累计收益%'],
            name='基准累计收益%',
            line=dict(color=COLOR_BENCHMARK, width=2),
            hovertemplate='基准累计: %{y:.2f}%<extra></extra>'
        ), row=1, col=1, secondary_y=False)

        # ---- 子图①次轴：指数点位 + MA250 年线 ----
        # 合并自原子图②。放次坐标轴而非另起一图：点位与年线的相对位置
        # （乖离率的可视化）正是买卖信号的来源，与收益曲线对齐看才有意义。
        fig.add_trace(go.Scatter(
            x=df['日期'], y=df['收盘价'],
            name='基准点数（右轴）',
            line=dict(color=COLOR_PRICE, width=1.2),
            hovertemplate='基准点数: %{y:,.3f}<extra></extra>'
        ), row=1, col=1, secondary_y=True)
        if has_ma250:
            fig.add_trace(go.Scatter(
                x=df['日期'], y=df['MA250'],
                name='MA250 年线（右轴）',
                line=dict(color=COLOR_MA250, width=1.2, dash='dash'),
                hovertemplate='MA250: %{y:,.3f}<extra></extra>'
            ), row=1, col=1, secondary_y=True)

        # ---- 子图①：买卖时点（箭头，买红卖绿）----
        # 全部买入合成一条 trace、全部卖出合成一条（原先每个事件一条 trace，
        # 上百条 trace 既拖慢渲染又塞爆图例）。
        for direction, color, symbol, legend in (
            ('买入', COLOR_BUY, 'arrow-up', '买入时点'),
            ('卖出', COLOR_SELL, 'arrow-down', '卖出时点'),
        ):
            sub = events_df[events_df['方向'] == direction] if len(events_df) else events_df
            if len(sub) == 0:
                continue
            fig.add_trace(go.Scatter(
                x=pd.to_datetime(sub['日期']), y=sub['策略累计%'],
                mode='markers', name=legend,
                marker=dict(color=color, size=13, symbol=symbol,
                            line=dict(width=1, color='#333333')),
                customdata=np.stack([sub['类型'], sub['乖离率%']], axis=-1),
                hovertemplate=(f'<b>{direction}</b> %{{customdata[0]}}'
                               '（乖离率 %{customdata[1]:.1f}%）<extra></extra>')
            ), row=1, col=1, secondary_y=False)

        # ---- 子图②：相对收益 ----
        fig.add_trace(go.Scatter(
            x=df['日期'], y=df['相对收益%'],
            name='相对收益%（策略−基准）',
            line=dict(color=COLOR_RELATIVE, width=2),
            fill='tozeroy', fillcolor='rgba(0, 100, 0, 0.15)',
            hovertemplate='相对收益: %{y:.2f}%<extra></extra>'
        ), row=2, col=1)
        fig.add_hline(y=0, line_dash='dash', line_color='black',
                      line_width=1, row=2, col=1)

        # ---- 子图③：持仓比例 ----
        fig.add_trace(go.Scatter(
            x=df['日期'], y=df['持仓比例%'],
            name='持仓比例%',
            line=dict(color='#FF8C00', width=1.2),
            fill='tozeroy', fillcolor='rgba(255, 140, 0, 0.2)',
            hovertemplate='持仓比例: %{y:.1f}%<extra></extra>'
        ), row=3, col=1)
        if self.metrics is not None:
            # 平均仓位 = 静态混合基准的权重 w，画出来便于对照「策略实际暴露」
            fig.add_hline(y=self.metrics['混合基准权重%'], line_dash='dot',
                          line_color=COLOR_BLEND, line_width=1.5,
                          annotation_text=f"平均仓位 {self.metrics['混合基准权重%']:.1f}%",
                          annotation_position='top left',
                          row=3, col=1)

        fig.update_yaxes(title_text='累计收益率 (%)', row=1, col=1, secondary_y=False)
        fig.update_yaxes(title_text='指数点位', row=1, col=1, secondary_y=True,
                         showgrid=False)
        fig.update_yaxes(title_text='相对收益 (%)', row=2, col=1)
        fig.update_yaxes(title_text='持仓比例 (%)', row=3, col=1, range=[0, 105])
        fig.update_xaxes(title_text='日期', row=3, col=1)

        # 标题 / 图例分居上下两端，杜绝重叠：
        # 原先 title 在 y≈1 而 legend 也 yanchor='bottom', y=1.02，两者抢同一
        # 条带；且图例横排过长时会盖住子图①的标题。现在图例整体移到图底。
        fig.update_layout(
            title=dict(
                text=(f'策略表现时间维度分析　{start_str} ~ {end_str}'
                      f'<br><sub>共 {len(df)} 个交易日</sub>'),
                x=0.5, xanchor='center', y=0.985, yanchor='top',
                font=dict(size=20),
            ),
            hovermode='x unified',
            template='plotly_white',
            width=1500,
            height=1150,
            margin=dict(t=110, b=110),
            legend=dict(orientation='h', yanchor='top', y=-0.07,
                        xanchor='center', x=0.5),
        )

        # 两张图写进同一个 HTML：上面总体表现，下面时间维度
        html_a = fig_a.to_html(full_html=False, include_plotlyjs='cdn')
        html_b = fig.to_html(full_html=False, include_plotlyjs=False)
        with open(save_path, 'w', encoding='utf-8') as f:
            f.write(
                '<!DOCTYPE html><html><head><meta charset="utf-8">'
                '<title>时间维度分析_综合可视化</title>'
                '<style>body{margin:0;padding:12px 0;'
                'font-family:"Microsoft YaHei",sans-serif;background:#fff;}'
                '</style></head><body>'
                f'{html_a}<hr style="margin:24px 60px;border:none;'
                'border-top:1px solid #ddd;">'
                f'{html_b}</body></html>'
            )
        print(f"  综合可视化: {save_path}")
        return save_path

    def _build_summary_figure(self, c_strategy, c_benchmark, c_blend):
        """总体表现：表格 + 三组柱状图（可视化总结）

        柱状图分三组而不是挤成一张：累计总收益（数量级 ~10²）、年化/波动/
        回撤（~10¹）、夏普/索提诺（~10⁰）差三个数量级，同轴会把后两组压成
        贴地的一条线，看不出任何差异。
        """
        cols, rows, diffs, _note, _w = self.overall_table()
        names = list(rows.keys())
        colors = [c_strategy, c_benchmark, c_blend][:len(names)]

        fig = make_subplots(
            rows=2, cols=3,
            row_heights=[0.46, 0.54],
            vertical_spacing=0.14, horizontal_spacing=0.08,
            specs=[[{'type': 'table', 'colspan': 3}, None, None],
                   [{'type': 'bar'}, {'type': 'bar'}, {'type': 'bar'}]],
            subplot_titles=('', '① 累计总收益率 (%)',
                            '② 年化收益 / 波动 / 回撤幅度 (%)',
                            '③ 风险调整后收益（比率）'),
        )

        # ---------- 表格 ----------
        header = ['　'] + cols
        cells = [names + list(diffs.keys())]
        for j, (disp, key, higher_better, unit) in enumerate(self._OVERALL_SPEC):
            col_vals = [f"{rows[n][key]:,.2f}{unit}" for n in names]
            for dlabel, dvals in diffs.items():
                delta, better = dvals[j]
                mark = '优' if better else '劣'
                col_vals.append(f"{delta:+,.2f}{unit} {mark}")
            cells.append(col_vals)

        n_base = len(names)
        fill = ([['#F5F7FA'] * n_base + ['#FFF7E6'] * len(diffs)]
                + [['white'] * n_base + ['#FFF7E6'] * len(diffs)] * len(cols))
        font_colors = [['#222'] * (n_base + len(diffs))]
        for j in range(len(cols)):
            fc = ['#222'] * n_base
            for dlabel, dvals in diffs.items():
                fc.append('#C62828' if dvals[j][1] else '#2E7D32')
            font_colors.append(fc)

        fig.add_trace(go.Table(
            columnwidth=[130] + [100] * len(cols),
            header=dict(values=[f'<b>{h}</b>' for h in header],
                        fill_color='#37474F', font=dict(color='white', size=13),
                        align='center', height=30),
            cells=dict(values=cells, fill_color=fill,
                       font=dict(color=font_colors, size=12),
                       align='center', height=27),
        ), row=1, col=1)

        # ---------- 柱状图 ----------
        groups = [
            (1, ['总收益率'], '%'),
            (2, ['年化收益率', '年化波动率', '最大回撤'], '%'),
            (3, ['夏普比率', '索提诺比率'], ''),
        ]
        disp2key = {d: k for d, k, _b, _u in self._OVERALL_SPEC}
        for col_idx, labels, unit in groups:
            for name, color in zip(names, colors):
                vals = []
                for lb in labels:
                    v = rows[name][disp2key[lb]]
                    # 回撤是负数，取绝对值作「回撤幅度」，柱子朝上更易比高低
                    vals.append(abs(v) if lb == '最大回撤' else v)
                fig.add_trace(go.Bar(
                    x=[lb if lb != '最大回撤' else '最大回撤幅度' for lb in labels],
                    y=vals, name=name, marker_color=color,
                    legendgroup=name, showlegend=(col_idx == 1),
                    text=[f'{v:,.2f}' for v in vals],
                    textposition='outside', cliponaxis=False,
                    hovertemplate=f'{name} %{{x}}: %{{y:,.2f}}{unit}<extra></extra>',
                ), row=2, col=col_idx)

        fig.update_layout(
            title=dict(text='总体表现对照（策略 / 满仓基准 / 同仓位静态混合）',
                       x=0.5, xanchor='center', y=0.98, yanchor='top',
                       font=dict(size=20)),
            barmode='group', template='plotly_white',
            width=1500, height=680, margin=dict(t=90, b=90),
            legend=dict(orientation='h', yanchor='top', y=-0.08,
                        xanchor='center', x=0.5),
        )
        return fig

    def generate_report(self, save_path):
        """生成 markdown 分析报告（锚点目录 + 阶段表 + 关键事件 + 参数与成本）

        2026-08-23 重构：原 {stock}_滚动仓位回测指标.txt 的全部内容并入本报告
        （第 1 节三方对照表、第 6 节策略参数、第 7 节交易与成本统计），
        每组产物从 6 个文件降到 4 个，不必再在 txt 与 md 之间来回对照。
        """
        phases_df = self.analyze_phases()
        events_df = self.identify_key_events()
        m = self.metrics

        with open(save_path, 'w', encoding='utf-8') as f:
            f.write("# 策略表现时间维度分析报告\n\n")

            # ---------- 基础信息 ----------
            initial_price = self.df['收盘价'].iloc[0]
            final_price = self.df['收盘价'].iloc[-1]
            f.write(f"**起始日期**: {self.df['日期'].iloc[0].strftime('%Y-%m-%d')}  \n")
            f.write(f"**起始价格**: {initial_price:,.3f}（基准累计收益率 0% 锚点）  \n")
            f.write(f"**结束日期**: {self.df['日期'].iloc[-1].strftime('%Y-%m-%d')}  \n")
            f.write(f"**结束价格**: {final_price:,.3f}  \n")
            # 年数口径与回测器一致（Bug H：交易日/年由数据实测，本数据约 243
            # 而非 252）。没有 metrics 时同样实测，不再写死 /252 ——
            # 否则报告开头与第 6 节会给出两个不同的年数（曾差 0.37 年）。
            if m is not None:
                _years = m['回测年数']
            else:
                _cal = (self.df['日期'].iloc[-1] - self.df['日期'].iloc[0]).days / 365.25
                _years = _cal if _cal > 0 else len(self.df) / 243.0
            f.write(f"**回测交易日数**: {len(self.df)} 个（约 {_years:.2f} 年）  \n")
            if m is not None:
                f.write(f"**最终资产**: {m['最终资产']:,.0f} 元"
                        f"（初始 {m['初始资金']:,.0f} 元）  \n")
            f.write("\n")

            # ---------- 锚点目录 ----------
            # GitHub / VSCode / Typora 的 markdown 锚点规则：小写、空格转 -、
            # 去掉标点。中文标题直接用原文即可命中。
            f.write("## 目录\n\n")
            f.write("- [1. 总体表现（策略 / 满仓基准 / 静态混合）](#1-总体表现策略--满仓基准--静态混合)\n")
            f.write("- [2. 市场阶段分析（核心）](#2-市场阶段分析核心)\n")
            f.write("  - [2.1 策略跑赢的阶段](#21-策略跑赢的阶段按超额收益降序)\n")
            f.write("  - [2.2 策略跑输的阶段](#22-策略跑输的阶段按超额收益升序)\n")
            f.write("- [3. 关键操作事件（所有买卖时点）](#3-关键操作事件所有买卖时点)\n")
            f.write("- [4. 策略行为模式总结](#4-策略行为模式总结)\n")
            f.write("- [5. 滚动指标极值（252日窗口）](#5-滚动指标极值252日窗口)\n")
            f.write("- [6. 策略参数](#6-策略参数)\n")
            f.write("- [7. 交易与成本统计](#7-交易与成本统计)\n\n")
            f.write("---\n\n")

            # ==========================================================
            # 1. 总体表现（三方对照表）
            # ==========================================================
            f.write("## 1. 总体表现（策略 / 满仓基准 / 静态混合）\n\n")
            cols, rows, diffs, note, blend_w = self.overall_table()

            f.write("| 口径 | " + " | ".join(cols) + " |\n")
            f.write("|" + "------|" * (len(cols) + 1) + "\n")
            disp2key = {d: k for d, k, _b, _u in self._OVERALL_SPEC}
            unit_of = {d: u for d, _k, _b, u in self._OVERALL_SPEC}
            for name in rows:
                vals = [f"{rows[name][disp2key[c]]:,.2f}{unit_of[c]}" for c in cols]
                f.write(f"| **{name}** | " + " | ".join(vals) + " |\n")
            for dlabel, dvals in diffs.items():
                cells = []
                for c, (delta, better) in zip(cols, dvals):
                    mark = "✅优" if better else "❌劣"
                    cells.append(f"{delta:+,.2f}{unit_of[c]} {mark}")
                f.write(f"| *{dlabel}* | " + " | ".join(cells) + " |\n")
            f.write("\n")

            f.write("> 差值行 = **策略 − 对照**。判优方向：收益类与夏普/索提诺"
                    "越大越好；波动率越小越好；最大回撤为负数，越接近 0 越好。\n\n")

            if note:
                f.write(f"> ⚠️ {note}\n\n")
            else:
                f.write(f"**两个对照组分别回答什么问题**\n\n")
                f.write(f"- **满仓基准**（100% 持有指数）：回答\"不如直接躺着拿指数？\"。"
                        f"与策略【风险暴露不对等】——策略日均仓位仅 {blend_w:.1f}%。\n")
                f.write(f"- **同仓位静态混合**（{blend_w:.1f}% 指数 + {100-blend_w:.1f}% 现金，"
                        f"期初买入后持有到底、不做任何择时、零交易）：把仓位差异抵消掉，"
                        f"剩下的差额才是【择时贡献】。这是 Henriksson–Merton (1981) "
                        f"择时检验的 buy-and-hold 对照组。\n\n")
                f.write(f"  即：`策略 − 满仓指数 = 择时贡献 + 现金拖累`（混在一起），"
                        f"`策略 − 同仓位混合 = 择时贡献`。\n\n")
                f.write(f"> ⚠️ **静态混合基准只能用来比【收益类】指标**"
                        f"（累计收益、年化收益）。均值匹配对线性统计量成立，但"
                        f"**最大回撤是尾部统计量，不能用它评价**：策略仓位是双峰分布"
                        f"（大量交易日接近满仓、也有不少完全空仓），回撤由回撤窗口内的"
                        f"【峰值暴露】决定，而混合基准全程只有 {blend_w:.1f}% 的暴露。"
                        f"拿两者比回撤，量的是仓位分布形状，不是择时能力。"
                        f"**回撤请与满仓基准比**。\n\n")
                f.write(f"> ⚠️ w = {blend_w:.1f}% 是策略【事后】实测的日均仓位，"
                        f"起始日无法预知，故静态混合**不是一个可投资的替代方案**，"
                        f"而是一个【归因工具】。\n\n")
                f.write(f"> 📌 注意静态混合与满仓基准的**夏普/索提诺几乎相同**"
                        f"（表中两行差 <0.01）。这不是巧合：静态混合与满仓指数在"
                        f"同一条资本配置线上，超额收益与波动同比例缩放，比率不变。"
                        f"换言之，**单纯降低仓位无法改善风险调整后收益** —— "
                        f"策略的夏普优势因此只能来自择时，不可能来自\"没满仓\"。\n\n")

            f.write("**相对收益轨迹**\n\n")
            f.write(f"- 最终相对收益（策略 − 满仓基准）: {self.df['相对收益%'].iloc[-1]:.2f}%\n")
            f.write(f"- 历史最大相对收益: {self.df['相对收益%'].max():.2f}%\n")
            f.write(f"- 历史最小相对收益: {self.df['相对收益%'].min():.2f}%\n\n")

            # ==========================================================
            # 2. 市场阶段分析
            # ==========================================================
            f.write("## 2. 市场阶段分析（核心）\n\n")
            f.write("每个阶段统计策略/基准的阶段收益、超额收益、最大回撤、仓位暴露。\n\n")
            f.write("| 阶段 | 关键事件 | 时间段 | 交易日 | 策略收益% | 基准收益% | 超额% | 策略回撤% | 基准回撤% | 仓位中位% | 买/卖 |\n")
            f.write("|------|---------|--------|--------|----------|----------|-------|----------|----------|----------|------|\n")
            for _, r in phases_df.iterrows():
                # 用emoji标记超额收益正负
                win_flag = "✅" if r['超额阶段收益%'] > 0 else "❌"
                f.write(
                    f"| {r['阶段']} | {r['关键事件']} | {r['时间段']} | {r['交易日数']} | "
                    f"{r['策略阶段收益%']:.2f} | {r['基准阶段收益%']:.2f} | "
                    f"{win_flag} **{r['超额阶段收益%']:.2f}** | "
                    f"{r['策略最大回撤%']:.2f} | {r['基准最大回撤%']:.2f} | "
                    f"{r['仓位中位数%']:.1f} | {r['买入操作']}/{r['卖出操作']} |\n"
                )

            # 胜负统计
            win_phases = phases_df[phases_df['超额阶段收益%'] > 0]
            lose_phases = phases_df[phases_df['超额阶段收益%'] <= 0]
            f.write(f"\n**胜负统计**: 策略跑赢 **{len(win_phases)}/{len(phases_df)}** 个阶段，跑输 **{len(lose_phases)}/{len(phases_df)}** 个阶段\n\n")

            # 详细分析：跑赢阶段
            if len(win_phases) > 0:
                f.write("### 2.1 策略跑赢的阶段（按超额收益降序）\n\n")
                sorted_wins = win_phases.sort_values('超额阶段收益%', ascending=False)
                for i, (_, r) in enumerate(sorted_wins.iterrows(), 1):
                    f.write(f"**TOP{i}: {r['阶段']}** | 超额收益 **+{r['超额阶段收益%']:.2f}%**\n\n")
                    f.write(f"- 时间段: {r['时间段']}（{r['交易日数']} 个交易日）\n")
                    f.write(f"- 关键事件: {r['关键事件']}\n")
                    f.write(f"- 策略阶段收益: **{r['策略阶段收益%']:.2f}%** / 基准阶段收益: **{r['基准阶段收益%']:.2f}%**\n")
                    f.write(f"- 策略最大回撤: {r['策略最大回撤%']:.2f}% / 基准最大回撤: {r['基准最大回撤%']:.2f}%（回撤更浅 {abs(r['基准最大回撤%'])-abs(r['策略最大回撤%']):+.2f}pp）\n")
                    f.write(f"- 仓位中位数: {r['仓位中位数%']:.1f}%\n")
                    f.write(f"- 买入操作 {r['买入操作']} 次，卖出操作 {r['卖出操作']} 次\n\n")

            # 详细分析：跑输阶段
            if len(lose_phases) > 0:
                f.write("### 2.2 策略跑输的阶段（按超额收益升序）\n\n")
                sorted_loses = lose_phases.sort_values('超额阶段收益%', ascending=True)
                for i, (_, r) in enumerate(sorted_loses.iterrows(), 1):
                    f.write(f"**BOT{i}: {r['阶段']}** | 超额收益 **{r['超额阶段收益%']:.2f}%**\n\n")
                    f.write(f"- 时间段: {r['时间段']}（{r['交易日数']} 个交易日）\n")
                    f.write(f"- 关键事件: {r['关键事件']}\n")
                    f.write(f"- 策略阶段收益: **{r['策略阶段收益%']:.2f}%** / 基准阶段收益: **{r['基准阶段收益%']:.2f}%**\n")
                    f.write(f"- 仓位中位数: {r['仓位中位数%']:.1f}%\n")
                    f.write(f"- 原因分析: 策略在该阶段仓位不足/错过上涨，或基准短期暴涨\n\n")

            # ==========================================================
            # 3. 关键操作事件
            # ==========================================================
            f.write("## 3. 关键操作事件（所有买卖时点）\n\n")
            f.write("| 日期 | 类型 | 方向 | 乖离率% | 策略累计% | 基准累计% | 相对收益% |\n")
            f.write("|------|------|------|---------|----------|----------|----------|\n")
            for _, e in events_df.iterrows():
                f.write(
                    f"| {e['日期']} | {e['类型']} | {e['方向']} | "
                    f"{e['乖离率%']:.2f} | {e['策略累计%']:.2f} | {e['基准累计%']:.2f} | "
                    f"{e['相对收益%']:.2f} |\n"
                )

            # ==========================================================
            # 4. 策略行为模式
            # ==========================================================
            f.write("\n## 4. 策略行为模式总结\n\n")
            buy_events = events_df[events_df['方向'] == '买入']
            sell_events = events_df[events_df['方向'] == '卖出']
            f.write(f"- **买入触发次数**: {len(buy_events)} 次\n")
            f.write(f"- **卖出触发次数**: {len(sell_events)} 次\n")
            if len(buy_events) > 0:
                avg_buy_div = buy_events['乖离率%'].mean()
                f.write(f"- **买入时乖离率均值**: {avg_buy_div:.2f}%（应为负值，表示在年线下方买入）\n")
            if len(sell_events) > 0:
                avg_sell_div = sell_events['乖离率%'].mean()
                f.write(f"- **卖出时乖离率均值**: {avg_sell_div:.2f}%（应为正值，表示在年线上方卖出）\n")
            f.write(f"- **日均仓位**: {self.df['持仓比例%'].mean():.2f}%"
                    f"（中位数 {self.df['持仓比例%'].median():.2f}%）\n")
            _near_full = (self.df['持仓比例%'] > 95).mean() * 100
            _empty = (self.df['持仓比例%'] < 1).mean() * 100
            f.write(f"- **仓位分布**: {_near_full:.1f}% 的交易日接近满仓（>95%），"
                    f"{_empty:.1f}% 的交易日空仓（<1%）"
                    f"——双峰分布，故日均仓位不代表典型仓位\n")

            # ==========================================================
            # 5. 滚动指标极值
            # ==========================================================
            f.write("\n## 5. 滚动指标极值（252日窗口）\n\n")
            rolling_df = self.compute_rolling_metrics()
            f.write(f"- **最大滚动252日策略收益**: {rolling_df['滚动252日策略收益%'].max():.2f}%\n")
            f.write(f"- **最小滚动252日策略收益**: {rolling_df['滚动252日策略收益%'].min():.2f}%\n")
            f.write(f"- **最大滚动252日基准收益**: {rolling_df['滚动252日基准收益%'].max():.2f}%\n")
            f.write(f"- **最小滚动252日基准收益**: {rolling_df['滚动252日基准收益%'].min():.2f}%\n")
            f.write(f"- **滚动252日超额收益极值**: {rolling_df['滚动252日超额%'].max():.2f}% / {rolling_df['滚动252日超额%'].min():.2f}%\n")
            f.write(f"- **滚动252日策略波动率区间**: {rolling_df['滚动252日策略波动%'].min():.2f}% ~ {rolling_df['滚动252日策略波动%'].max():.2f}%\n")
            f.write(f"- **滚动252日基准波动率区间**: {rolling_df['滚动252日基准波动%'].min():.2f}% ~ {rolling_df['滚动252日基准波动%'].max():.2f}%\n")

            # ==========================================================
            # 6~7. 原 {stock}_滚动仓位回测指标.txt 并入
            # ==========================================================
            self._write_params_section(f)
            self._write_cost_section(f)

        print(f"  分析报告: {save_path}")
        return save_path

    def _write_params_section(self, f):
        """第 6 节：策略参数（原 txt 的「策略参数」块）"""
        f.write("\n## 6. 策略参数\n\n")
        bt = self.bt
        if bt is None:
            f.write("> 本次分析未接入回测器实例，策略参数不可用。"
                    "如需完整参数，请通过 `PerformanceAnalyzer.from_backtest(csv, bt)` "
                    "构造，或直接运行 `scripts/backtest/run_*_backtests.py`。\n")
            return
        m = self.metrics or {}
        f.write("| 参数 | 值 | 含义 |\n|------|-----|------|\n")
        f.write(f"| 初始资金 | {bt.initial_capital:,.0f} 元 | — |\n")
        f.write(f"| 定投天数 n | {bt.invest_days} 个交易日 | 触发买入后分 n 个交易日建仓 |\n")
        f.write(f"| 第一卖出阈值 a | {bt.sell_threshold_a}% | 乖离率 ≥ a 时卖出 50% |\n")
        f.write(f"| 第二卖出阈值 b | {bt.sell_threshold_b}% | 乖离率 ≥ b 时清仓 |\n")
        f.write(f"| 空仓年化收益 c | {bt.cash_return_rate}% | 空仓资金按此年化计息 |\n")
        f.write(f"| 起始日期 | {bt.start_date.strftime('%Y-%m-%d') if bt.start_date else '数据首日'} | — |\n")
        f.write(f"| 结束日期 | {bt.end_date.strftime('%Y-%m-%d') if bt.end_date else '数据末日'} | — |\n")
        f.write(f"| 深度定投档位 | {bt.dca_tiers if bt.dca_tiers else '关闭（全 1×）'} | (乖离率阈值, 倍数)，越跌买越多 |\n")
        f.write(f"| 全仓买入阈值 | {bt.lump_sum_threshold:,.0f} 元 | 剩余现金低于此值时一次性买入，不再分批 |\n")
        f.write(f"| 浮点噪声门槛 | {bt.noise_threshold:,.0f} 元 | 低于此值的残留现金视为噪声，忽略信号 |\n")
        if m:
            f.write(f"\n**回测区间**: {m['起始日期'].strftime('%Y-%m-%d')} ~ "
                    f"{m['结束日期'].strftime('%Y-%m-%d')}，共 {m['回测天数']} 个交易日"
                    f"（约 {m['回测年数']:.2f} 年）  \n")
            f.write(f"**起始价格**: {m['起始价格(基准0%锚点)']:,.3f}（基准 0% 锚点） → "
                    f"**结束价格**: {m['结束价格']:,.3f}\n")

    def _write_cost_section(self, f):
        """第 7 节：交易与成本统计（原 txt 的「交易统计」+「交易成本统计」块）"""
        f.write("\n## 7. 交易与成本统计\n\n")
        m, bt = self.metrics, self.bt
        if m is None:
            f.write("> 本次分析未接入回测器指标，交易成本统计不可用"
                    "（成本数据来自回测器的 trading_records，不在每日记录 CSV 中）。\n")
            return

        f.write("### 7.1 交易次数\n\n")
        f.write(f"- **总交易次数**: {m['交易次数']}\n")
        f.write(f"  - 买入次数（定投类）: {m['买入次数']}\n")
        f.write(f"  - 全仓买入次数（小资金）: {m['🆕全仓买入次数']}\n")
        f.write(f"  - 卖出次数: {m['卖出次数']}\n")
        f.write(f"- **平均资金使用率（日均仓位）**: {m['平均资金使用率']:.2f}%\n")
        if bt is not None and bt.dca_tiers:
            f.write(f"- **深度定投倍数分布**: 1× {m['1×定投次数']} 次 / "
                    f"2× {m['2×定投次数']} 次 / 3× {m['3×定投次数']} 次")
            if m['其他倍数定投次数'] > 0:
                f.write(f" / 其他 {m['其他倍数定投次数']} 次")
            f.write("\n")

        f.write("\n### 7.2 交易成本\n\n")
        if bt is None or not bt.enable_trading_costs:
            f.write("交易成本建模: **关闭**\n")
            return

        f.write("**费率设置**\n\n")
        f.write(f"- 佣金率（名义，单边）: {bt.commission_rate*100:.4f}%（买卖双边收取）\n")
        if bt.stamp_duty_exempt:
            f.write(f"- 印花税: 免征（{self._stock_label()} 为 ETF/基金份额）\n")
        else:
            f.write(f"- 印花税率: {bt.stamp_duty_rate*100:.4f}%（仅卖出方缴纳，买入不征）\n")
        f.write(f"- 最低佣金: {bt.min_commission:.2f} 元/笔\n\n")

        f.write("**成本汇总**\n\n")
        f.write(f"- 总佣金支付: {m['总佣金']:,.2f} 元\n")
        f.write(f"- 总印花税支付: {m['总印花税']:,.2f} 元\n")
        f.write(f"- **总交易成本**: {m['总交易成本']:,.2f} 元\n")
        f.write(f"- 含费用交易笔数: {m['含费用交易笔数']} 笔\n")
        if m['含费用交易笔数']:
            f.write(f"- 平均每笔成本: {m['总交易成本']/m['含费用交易笔数']:.2f} 元/笔\n")

        if m.get('实际佣金率%') is not None:
            f.write(f"\n**⚠️ 实际佣金率（最低佣金效应）**\n\n")
            f.write(f"- 触发 {bt.min_commission:.0f} 元下限笔数: "
                    f"{m['触发最低佣金笔数']} / {m['含费用交易笔数']} 笔"
                    f"（{m['触发最低佣金占比%']:.1f}%）\n")
            f.write(f"- 实际佣金 / 成交额: **{m['实际佣金率%']:.4f}%**，为名义 "
                    f"{bt.commission_rate*100:.4f}% 的 "
                    f"{m['实际佣金率%']/(bt.commission_rate*100):.1f} 倍\n")
            f.write(f"- 说明: n={bt.invest_days} 的分批定投使单笔金额过小，"
                    f"绝大多数笔数触发最低佣金 —— 这是**实盘经济性问题，非建模误差**\n")

        f.write(f"\n**成本占比**\n\n")
        f.write(f"- 总成本 / 初始资金: {m['总成本占初始资金比例']:.2f}%\n")
        f.write(f"- 总佣金 / 初始资金: {m['佣金占初始资金比例']:.2f}%\n")
        if m['总成本占最绔回报比例'] != float('inf'):
            f.write(f"- 总成本 / 最终回报: {m['总成本占最绔回报比例']:.2f}%\n")
        else:
            f.write(f"- 总成本 / 最终回报: N/A（策略亏损）\n")

    def _stock_label(self):
        return getattr(self.bt, 'stock_name', None) or '本标的'


# ============ 主程序 ============
if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='策略表现时间维度分析')
    parser.add_argument('daily_records', nargs='?', default='output/backtests/h20269/2015-05起_深度定投策略/H20269_滚动仓位每日记录.csv',
                        help='回测每日记录CSV路径')
    parser.add_argument('--output-dir', default=None, help='输出目录（默认与CSV同目录）')
    args = parser.parse_args()

    csv_path = args.daily_records
    if args.output_dir is None:
        output_dir = os.path.dirname(csv_path)
    else:
        output_dir = args.output_dir
        os.makedirs(output_dir, exist_ok=True)

    print("=" * 60)
    print("策略表现时间维度分析")
    print("=" * 60)
    print(f"输入: {csv_path}")
    print(f"输出目录: {output_dir}")

    analyzer = PerformanceAnalyzer(csv_path)

    # 1. 阶段分析
    print("\n--- 阶段分析 ---")
    phases = analyzer.analyze_phases()
    print(phases.to_string(index=False))

    # 2. 关键事件
    print("\n--- 关键操作事件 ---")
    events = analyzer.identify_key_events()
    print(events.to_string(index=False))

    # 3. 生成可视化HTML
    html_path = os.path.join(output_dir, '时间维度分析_综合可视化.html')
    analyzer.plot_analysis(html_path)

    # 4. 生成markdown报告
    report_path = os.path.join(output_dir, '时间维度分析报告.md')
    analyzer.generate_report(report_path)

    print(f"\n✅ 分析完成！")
    print(f"  - 综合可视化: {html_path}")
    print(f"  - 分析报告: {report_path}")
