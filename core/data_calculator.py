# -*- coding: utf-8 -*-
"""
250日均线数据计算模块
功能：
1. 加载CSV数据
2. 计算250日均线
3. 计算年线乖离率
4. 🆕 计算RSI指标（Wilder平滑法，多周期，备用指标）
5. 识别跌破年线和重回年线事件
6. 计算跌破年线买入的收益率统计
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


import pandas as pd
import numpy as np
from datetime import datetime
import os


class MA250DataCalculator:
    """250日均线数据计算器"""

    def __init__(self, csv_file_path):
        """
        初始化计算器

        参数：
        csv_file_path: CSV文件路径
        """
        self.csv_file_path = csv_file_path
        self.df = None
        self.stock_name = None

        # 从文件名提取标的名称
        self._extract_stock_name()

    def _extract_stock_name(self):
        """从CSV文件名中提取标的名称"""
        file_name = os.path.basename(self.csv_file_path)
        # 移除.csv后缀和"历史数据"等字样
        name = file_name.replace('.csv', '').replace('历史数据', '').strip()
        self.stock_name = name

    def load_data(self):
        """加载CSV数据"""
        try:
            print(f"正在读取文件: {self.csv_file_path}")
            self.df = pd.read_csv(self.csv_file_path, encoding='utf-8-sig')

            # 转换日期格式
            self.df['日期'] = pd.to_datetime(self.df['日期'])

            # 转换收盘价为数值
            self.df['收盘'] = pd.to_numeric(self.df['收盘'], errors='coerce')

            # 按日期排序（确保时间顺序正确）
            self.df = self.df.sort_values('日期')
            self.df = self.df.reset_index(drop=True)

            print(f"数据加载成功，共 {len(self.df)} 条记录")
            print(f"日期范围: {self.df['日期'].min()} 至 {self.df['日期'].max()}")
            return True

        except Exception as e:
            print(f"数据加载失败: {e}")
            return False

    def calculate_ma250(self):
        """计算250日均线"""
        if self.df is None:
            print("请先加载数据")
            return False

        print("正在计算250日均线...")
        self.df['MA250'] = self.df['收盘'].rolling(window=250).mean()

        # 只保留有MA250数据的行（前250行数据不足）
        self.df = self.df.dropna(subset=['MA250']).reset_index(drop=True)

        print(f"计算完成，有效数据: {len(self.df)} 条")
        return True

    def calculate_divergence(self):
        """计算年线乖离率"""
        if 'MA250' not in self.df.columns:
            print("请先计算MA250")
            return False

        print("正在计算年线乖离率...")
        # 乖离率 = (收盘价 - MA250) / MA250 * 100%
        self.df['乖离率'] = ((self.df['收盘'] - self.df['MA250']) / self.df['MA250']) * 100

        print("乖离率计算完成")
        return True

    def calculate_rsi(self, periods=None):
        """
        计算RSI指标（Wilder平滑法，避免出现0或100极端值）

        参数：
        periods: RSI计算周期列表，默认 [6, 12, 24]
                 - 6日：短线敏感（券商软件标准短线周期）
                 - 12日：中短线（券商软件标准周期）
                 - 24日：中线平滑（券商软件标准中线周期）
                 - 注：与同花顺/通达信/东方财富等券商软件一致，便于对照验证

        技术细节：
        1. 使用 Wilder 平滑（EMA with alpha=1/N），相比 SMA 更抗极端值
           - Wilder 是行业标准（TradingView/同花顺/通达信 都用这个）
           - 公式：avg[t] = (avg[t-1] * (N-1) + current) / N
           - 等价于 pandas ewm(alpha=1/N, adjust=False)
        2. 避免极端值的策略（三层防护）：
           - 第一层：Wilder 平滑本身减少极端值出现频率
           - 第二层：avg_gain 和 avg_loss 都做 clip(lower=eps)
                     eps=1e-6（足够小，不影响正常值精度）
           - 第三层：最终 RSI 硬性裁剪到 [0.01, 99.99]（防御性兜底）
           - 这样 RS 永远不会是 ∞ 或 0，RSI 永远在 (0, 100) 开区间内
        3. 数据前 N 日为 NaN（min_periods=period，数据不足不计算）

        返回：
        True 表示计算成功
        """
        if periods is None:
            periods = [6, 12, 24]

        if self.df is None or '收盘' not in self.df.columns:
            print("请先加载数据")
            return False

        print(f"正在计算RSI指标（周期: {periods}，Wilder平滑法）...")

        # 计算每日涨跌
        delta = self.df['收盘'].diff()
        gain = delta.where(delta > 0, 0.0)        # 上涨日的涨幅，下跌日为0
        loss = (-delta).where(delta < 0, 0.0)     # 下跌日的跌幅（取正），上涨日为0

        eps = 1e-6  # 极小值，避免除零

        for period in periods:
            # Wilder 平滑法（等价于 EMA with alpha=1/period）
            avg_gain = gain.ewm(
                alpha=1.0 / period,
                min_periods=period,
                adjust=False
            ).mean()
            avg_loss = loss.ewm(
                alpha=1.0 / period,
                min_periods=period,
                adjust=False
            ).mean()

            # 第二层防护：avg_gain 和 avg_loss 都做下限约束
            safe_avg_gain = avg_gain.clip(lower=eps)
            safe_avg_loss = avg_loss.clip(lower=eps)

            # 计算 RS 和 RSI
            rs = safe_avg_gain / safe_avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))

            # 第三层防护：硬性裁剪到 [0.01, 99.99]（理论上不应该触发）
            rsi = rsi.clip(lower=0.01, upper=99.99)

            col_name = f'RSI{period}'
            self.df[col_name] = rsi

            # 输出统计信息
            valid_rsi = rsi.dropna()
            if len(valid_rsi) > 0:
                # 统计极值出现频率（RSI > 80 或 < 20）
                overbought = (valid_rsi > 80).sum()
                oversold = (valid_rsi < 20).sum()
                print(f"  RSI{period}: 有效 {len(valid_rsi)} 条, "
                      f"范围 [{valid_rsi.min():.2f}, {valid_rsi.max():.2f}], "
                      f"均值 {valid_rsi.mean():.2f}, "
                      f">80:{overbought}条, <20:{oversold}条")

        print("RSI计算完成")
        return True

    def identify_break_events(self):
        """
        识别跌破年线和重回年线事件

        跌破年线：前一日收盘 > MA250，当日收盘 ≤ MA250
        重回年线：收盘价 > MA250

        返回：
        break_events: 完整的跌破/重回事件列表
        last_unfinished_break: 最后一次未完成的跌破事件（如果存在）
        """
        if self.df is None or 'MA250' not in self.df.columns:
            print("请先加载数据并计算MA250")
            return None, None

        print("正在识别跌破/重回年线事件...")

        break_events = []  # 完整的跌破/重回事件列表
        break_start = None  # 跌破开始的索引

        for i in range(1, len(self.df)):
            prev_close = self.df.loc[i-1, '收盘']
            prev_ma250 = self.df.loc[i-1, 'MA250']
            curr_close = self.df.loc[i, '收盘']
            curr_ma250 = self.df.loc[i, 'MA250']

            # 检测跌破年线
            if prev_close > prev_ma250 and curr_close <= curr_ma250:
                break_start = i
                print(f"  跌破年线: {self.df.loc[i, '日期'].strftime('%Y-%m-%d')}, 收盘={curr_close:.3f}, MA250={curr_ma250:.3f}")

            # 检测重回年线
            elif break_start is not None and curr_close > curr_ma250:
                # 记录一个完整的跌破区间
                event = {
                    'break_date': self.df.loc[break_start, '日期'],
                    'break_index': break_start,
                    'recover_date': self.df.loc[i, '日期'],
                    'recover_index': i,
                    'break_price': self.df.loc[break_start, '收盘'],
                    'recover_price': self.df.loc[i, '收盘'],
                }
                break_events.append(event)
                print(f"    重回年线: {self.df.loc[i, '日期'].strftime('%Y-%m-%d')}, 收盘={curr_close:.3f}, MA250={curr_ma250:.3f}, 跌破持续天数={i-break_start}天")

                break_start = None

        # 检查最后是否仍在跌破状态
        last_unfinished_break = None
        if break_start is not None:
            break_date = self.df.loc[break_start, '日期']
            # 记录未完成的跌破事件（截至数据最后一天）
            last_unfinished_break = {
                'break_date': break_date,
                'break_index': break_start,
                'break_price': self.df.loc[break_start, '收盘'],
                'end_date': self.df.loc[len(self.df) - 1, '日期'],  # 数据最后一天
                'end_index': len(self.df) - 1,
                'is_finished': False  # 标记为未完成
            }
            duration_days = len(self.df) - 1 - break_start
            print(f"  注意: 最后一次跌破({break_date.strftime('%Y-%m-%d')})尚未重回年线")
            print(f"    截至{self.df.loc[len(self.df) - 1, '日期'].strftime('%Y-%m-%d')}，已持续{duration_days}个交易日")

        print(f"\n共识别到 {len(break_events)} 个完整的跌破/重回年线区间")
        if last_unfinished_break:
            print(f"另有 1 个未完成的跌破区间（将在柱状图中单独显示）")

        return break_events, last_unfinished_break

    def calculate_return_stats(self):
        """
        计算跌破年线买入的收益率统计

        返回：
        stats: 统计结果字典
        details: 详细列表
        """
        if self.df is None or 'MA250' not in self.df.columns:
            print("请先加载数据并计算MA250")
            return None, None

        print("\n正在计算跌破年线买入的收益率...")

        returns_60 = []   # 60日收益率列表
        returns_120 = []  # 120日收益率列表
        details = []      # 详细列表

        for i in range(1, len(self.df)):
            prev_close = self.df.loc[i-1, '收盘']
            prev_ma250 = self.df.loc[i-1, 'MA250']
            curr_close = self.df.loc[i, '收盘']
            curr_ma250 = self.df.loc[i, 'MA250']

            # 检测跌破年线
            if prev_close > prev_ma250 and curr_close <= curr_ma250:
                buy_date = self.df.loc[i, '日期']
                buy_price = curr_close

                # 计算60日收益率
                if i + 60 < len(self.df):
                    price_60 = self.df.loc[i + 60, '收盘']
                    return_60 = ((price_60 - buy_price) / buy_price) * 100
                    returns_60.append(return_60)
                else:
                    return_60 = None  # 数据不足

                # 计算120日收益率
                if i + 120 < len(self.df):
                    price_120 = self.df.loc[i + 120, '收盘']
                    return_120 = ((price_120 - buy_price) / buy_price) * 100
                    returns_120.append(return_120)
                else:
                    return_120 = None  # 数据不足

                # 只统计能够完整计算收益率的跌破
                if return_60 is not None and return_120 is not None:
                    detail = {
                        '跌破日期': buy_date.strftime('%Y-%m-%d'),
                        '买入价格': f'{buy_price:.3f}',
                        '60日后价格': f'{price_60:.3f}',
                        '60日收益率': f'{return_60:.2f}%',
                        '120日后价格': f'{price_120:.3f}',
                        '120日收益率': f'{return_120:.2f}%',
                    }
                    details.append(detail)
                    print(f"  {buy_date.strftime('%Y-%m-%d')}: 买入={buy_price:.3f}, 60日收益={return_60:.2f}%, 120日收益={return_120:.2f}%")

        # 计算统计数据
        if returns_60 and returns_120:
            stats = {
                '60日平均收益率': f'{np.mean(returns_60):.2f}%',
                '60日收益率标准差': f'{np.std(returns_60):.2f}%',
                '120日平均收益率': f'{np.mean(returns_120):.2f}%',
                '120日收益率标准差': f'{np.std(returns_120):.2f}%',
                '样本数量': len(returns_60),
            }

            print(f"\n=== 收益率统计 ===")
            print(f"样本数量: {stats['样本数量']}")
            print(f"60日平均收益率: {stats['60日平均收益率']}")
            print(f"60日收益率标准差: {stats['60日收益率标准差']}")
            print(f"120日平均收益率: {stats['120日平均收益率']}")
            print(f"120日收益率标准差: {stats['120日收益率标准差']}")

            return stats, details
        else:
            print("没有找到足够的历史跌破数据用于统计")
            return None, details

    def get_data(self):
        """
        获取计算后的完整数据

        返回：
        df: 包含日期、收盘、MA250、乖离率等字段的DataFrame
        """
        if self.df is None:
            print("请先加载数据并完成计算")
            return None

        return self.df

    def run_calculations(self):
        """
        运行所有计算流程

        返回：
        df: 完整数据
        break_events: 跌破事件列表
        last_unfinished_break: 未完成事件
        stats: 收益率统计
        details: 详细收益记录
        """
        print("="*60)
        print(f"开始计算: {self.stock_name}")
        print("="*60)

        # 1. 加载数据
        if not self.load_data():
            return None, None, None, None, None

        # 2. 计算250日均线
        if not self.calculate_ma250():
            return None, None, None, None, None

        # 3. 计算乖离率
        if not self.calculate_divergence():
            return None, None, None, None, None

        # 4. 计算RSI指标（🆕 备用，不参与主策略）
        self.calculate_rsi()

        # 5. 识别跌破/重回年线事件
        break_events, last_unfinished_break = self.identify_break_events()

        # 6. 计算收益率统计
        stats, details = self.calculate_return_stats()

        print("\n" + "="*60)
        print("数据计算完成！")
        print("="*60)

        return self.df, break_events, last_unfinished_break, stats, details
