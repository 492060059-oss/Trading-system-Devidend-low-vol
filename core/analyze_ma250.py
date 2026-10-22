# -*- coding: utf-8 -*-
"""
标的与250日均线分析工具（画图模块）
功能：
1. 绘制价格走势 vs 250日均线（含跌破区间标注）
2. 绘制年线乖离率走势
3. 统计跌破年线买入的收益率
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
import matplotlib.pyplot as plt
from datetime import datetime
import os
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.express as px
from data_calculator import MA250DataCalculator

# 设置中文字体
plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'Arial Unicode MS']
plt.rcParams['axes.unicode_minus'] = False

# 定义颜色
COLOR_PRICE = '#00008B'  # 深蓝色
COLOR_MA250 = '#FF0000'   # 红色
COLOR_ZERO_AXIS = '#000000'  # 黑色
COLOR_POS_FILL = '#90EE90'   # 浅绿色
COLOR_NEG_FILL = '#FFB6C1'   # 浅红色
COLOR_SHADE = '#D3D3D3'      # 浅灰色（用于跌破区间标注）


class MA250Analyzer:
    """250日均线分析器（画图模块）"""

    def __init__(self, csv_file_path):
        """
        初始化分析器

        参数：
        csv_file_path: CSV文件路径
        """
        self.csv_file_path = csv_file_path
        self.df = None
        self.stock_name = None
        self.calculator = MA250DataCalculator(csv_file_path)
        self.break_events = []
        self.last_unfinished_break = None

        # 从计算器获取标的名称
        self.stock_name = self.calculator.stock_name

    def load_and_calculate(self):
        """加载并计算所有数据"""
        # 使用计算器运行所有计算
        self.df, self.break_events, self.last_unfinished_break, _, _ = self.calculator.run_calculations()

        if self.df is None:
            return False

        return True

    def plot_chart1(self, save_path=None):
        """
        绘制图表1：价格走势 vs 250日均线（含跌破区间标注）

        参数：
        save_path: 保存路径，如果为None则显示图表
        """
        if self.df is None or 'MA250' not in self.df.columns:
            print("请先加载数据并计算")
            return

        print(f"\n正在绘制图表1: {self.stock_name} vs 250日均线走势")

        fig, ax = plt.subplots(figsize=(14, 7))

        # 绘制跌破年线区间的阴影标注（使用axvspan）
        for i, event in enumerate(self.break_events):
            break_date = event['break_date']
            recover_date = event['recover_date']

            # 使用axvspan绘制垂直区域
            ax.axvspan(
                break_date,
                recover_date,
                facecolor=COLOR_SHADE,
                alpha=0.3,
                label='跌破年线区间' if i == 0 else ''
            )

        # 绘制价格线（深蓝色）
        ax.plot(self.df['日期'], self.df['收盘'], color=COLOR_PRICE, linewidth=1.5, label=f'{self.stock_name}价格走势')

        # 绘制250日均线（红色）
        ax.plot(self.df['日期'], self.df['MA250'], color=COLOR_MA250, linewidth=2, label='250日均线')

        # 设置标题和标签
        ax.set_title(f'{self.stock_name} vs 250日均线走势', fontsize=14, fontweight='bold')
        ax.set_xlabel('日期', fontsize=12)
        ax.set_ylabel('价格', fontsize=12)

        # 设置网格
        ax.grid(True, linestyle='--', alpha=0.7)
        ax.set_facecolor('white')

        # 设置图例
        ax.legend(loc='best', fontsize=10)

        # 横坐标：按适当间隔显示年-月
        import matplotlib.dates as mdates
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
        ax.xaxis.set_major_locator(mdates.AutoDateLocator())

        plt.tight_layout()

        if save_path:
            # 保存为多种格式
            base_path = save_path.rsplit('.', 1)[0]  # 移除扩展名

            # PNG格式（栅格图）
            png_path = f"{base_path}.png"
            plt.savefig(png_path, dpi=100, bbox_inches='tight')
            print(f"  PNG格式: {png_path}")

            # PDF格式（矢量图，可编辑）
            pdf_path = f"{base_path}.pdf"
            plt.savefig(pdf_path, format='pdf', bbox_inches='tight')
            print(f"  PDF格式: {pdf_path}")

            # SVG格式（矢量图，可编辑）
            svg_path = f"{base_path}.svg"
            plt.savefig(svg_path, format='svg', bbox_inches='tight')
            print(f"  SVG格式: {svg_path}")
        else:
            plt.show()

        plt.close()

    def plot_chart2(self, save_path=None):
        """
        绘制图表2：年线乖离率走势

        参数：
        save_path: 保存路径，如果为None则显示图表
        """
        if self.df is None or '乖离率' not in self.df.columns:
            print("请先加载数据并计算乖离率")
            return

        print(f"\n正在绘制图表2: {self.stock_name} 年线乖离率走势")

        fig, ax = plt.subplots(figsize=(14, 7))

        # 绘制乖离率曲线（深蓝色）
        ax.plot(self.df['日期'], self.df['乖离率'], color=COLOR_PRICE, linewidth=1.5, label='年线乖离率')

        # 绘制0基准线（黑色）
        ax.axhline(y=0, color=COLOR_ZERO_AXIS, linewidth=1.5, linestyle='-', label='0基准线')

        # 区域填充：高于250日线的部分为绿色，低于250日线的部分为红色
        # 高于年线（乖离率>0）
        ax.fill_between(
            self.df['日期'],
            0,
            self.df['乖离率'],
            where=(self.df['乖离率'] > 0),
            facecolor=COLOR_POS_FILL,
            alpha=0.5,
            label='高于年线'
        )

        # 低于年线（乖离率<0）
        ax.fill_between(
            self.df['日期'],
            0,
            self.df['乖离率'],
            where=(self.df['乖离率'] < 0),
            facecolor=COLOR_NEG_FILL,
            alpha=0.5,
            label='低于年线'
        )

        # 设置标题和标签
        ax.set_title(f'{self.stock_name} 年线乖离率走势', fontsize=14, fontweight='bold')
        ax.set_xlabel('日期', fontsize=12)
        ax.set_ylabel('乖离率 (%)', fontsize=12)

        # 设置网格
        ax.grid(True, linestyle='--', alpha=0.7)
        ax.set_facecolor('white')

        # 设置图例
        ax.legend(loc='best', fontsize=10)

        # 横坐标：按适当间隔显示年-月
        import matplotlib.dates as mdates
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
        ax.xaxis.set_major_locator(mdates.AutoDateLocator())

        plt.tight_layout()

        if save_path:
            # 保存为多种格式
            base_path = save_path.rsplit('.', 1)[0]  # 移除扩展名

            # PNG格式（栅格图）
            png_path = f"{base_path}.png"
            plt.savefig(png_path, dpi=100, bbox_inches='tight')
            print(f"  PNG格式: {png_path}")

            # PDF格式（矢量图，可编辑）
            pdf_path = f"{base_path}.pdf"
            plt.savefig(pdf_path, format='pdf', bbox_inches='tight')
            print(f"  PDF格式: {pdf_path}")

            # SVG格式（矢量图，可编辑）
            svg_path = f"{base_path}.svg"
            plt.savefig(svg_path, format='svg', bbox_inches='tight')
            print(f"  SVG格式: {svg_path}")
        else:
            plt.show()

        plt.close()

    def plot_chart3(self, save_path=None):
        """
        绘制图表3：跌破年线持续交易日长度柱状图

        参数：
        save_path: 保存路径，如果为None则显示图表
        """
        if not self.break_events and not self.last_unfinished_break:
            print("没有跌破年线事件数据，无法绘制柱状图")
            return

        print(f"\n正在绘制图表3: {self.stock_name} 跌破年线持续交易日长度")

        # 准备数据
        event_labels = []
        durations = []
        colors = []  # 每个柱子的颜色
        is_finished = []  # 标记是否完成

        # 添加已完成的跌破事件
        for i, event in enumerate(self.break_events):
            break_date = event['break_date'].strftime('%Y-%m-%d')
            duration = event['recover_index'] - event['break_index']
            event_labels.append(f"{break_date}")
            durations.append(duration)
            colors.append(COLOR_NEG_FILL)  # 浅红色表示已完成
            is_finished.append(True)
            print(f"  跌破事件{i+1}: {break_date}, 持续{duration}个交易日 (已完成)")

        # 添加未完成的跌破事件
        if self.last_unfinished_break:
            break_date = self.last_unfinished_break['break_date'].strftime('%Y-%m-%d')
            end_date = self.last_unfinished_break['end_date'].strftime('%Y-%m-%d')
            duration = self.last_unfinished_break['end_index'] - self.last_unfinished_break['break_index']
            event_labels.append(f"{break_date}")
            durations.append(duration)
            colors.append('#FFD700')  # 金黄色表示未完成
            is_finished.append(False)
            print(f"  跌破事件(未完成): {break_date}, 截至{end_date}已持续{duration}个交易日 (未完成)")

        # 创建图表
        fig, ax = plt.subplots(figsize=(14, 7))

        # 生成x轴位置
        x_positions = range(len(durations))

        # 分别绘制已完成和未完成的柱状图
        for i, (x_pos, duration, color, finished) in enumerate(zip(x_positions, durations, colors, is_finished)):
            label = '已完成跌破区间' if (finished and i == len(self.break_events) - 1 and not self.last_unfinished_break) or (finished and not self.last_unfinished_break and i == 0) else ('未完成跌破区间' if not finished else '')
            bar = ax.bar(
                x_pos,
                duration,
                color=color,
                edgecolor=COLOR_PRICE,
                linewidth=1.5,
                alpha=0.7,
                label=label if label else None
            )

            # 在每个柱子上标注具体数值
            height = duration
            ax.text(
                x_pos,
                height,
                f'{int(duration)}*' if not finished else f'{int(duration)}',
                ha='center',
                va='bottom',
                fontsize=9
            )

        # 手动设置图例
        from matplotlib.patches import Patch
        legend_elements = [
            Patch(facecolor=COLOR_NEG_FILL, edgecolor=COLOR_PRICE, label='已完成跌破区间'),
            Patch(facecolor='#FFD700', edgecolor=COLOR_PRICE, label='未完成跌破区间*')
        ]
        ax.legend(handles=legend_elements, loc='best', fontsize=10)

        # 设置x轴标签为日期
        ax.set_xticks(x_positions)
        ax.set_xticklabels(event_labels, rotation=45, ha='right', fontsize=8)

        # 设置标题和标签
        ax.set_title(f'{self.stock_name} 跌破年线持续交易日长度', fontsize=14, fontweight='bold')
        ax.set_xlabel('跌破年线日期', fontsize=12)
        ax.set_ylabel('持续交易日数', fontsize=12)

        # 设置网格
        ax.grid(True, linestyle='--', alpha=0.7, axis='y')
        ax.set_facecolor('white')

        plt.tight_layout()

        if save_path:
            # 保存为多种格式
            base_path = save_path.rsplit('.', 1)[0]  # 移除扩展名

            # PNG格式（栅格图）
            png_path = f"{base_path}.png"
            plt.savefig(png_path, dpi=100, bbox_inches='tight')
            print(f"  PNG格式: {png_path}")

            # PDF格式（矢量图，可编辑）
            pdf_path = f"{base_path}.pdf"
            plt.savefig(pdf_path, format='pdf', bbox_inches='tight')
            print(f"  PDF格式: {pdf_path}")

            # SVG格式（矢量图，可编辑）
            svg_path = f"{base_path}.svg"
            plt.savefig(svg_path, format='svg', bbox_inches='tight')
            print(f"  SVG格式: {svg_path}")
        else:
            plt.show()

        plt.close()

    def run_analysis(self, output_dir='output/analysis'):
        """
        运行完整分析流程

        参数：
        output_dir: 输出目录
        """
        print("="*60)
        print(f"开始分析: {self.stock_name}")
        print("="*60)

        # 创建输出目录
        os.makedirs(output_dir, exist_ok=True)

        # 1. 加载并计算数据
        if not self.load_and_calculate():
            return False

        # 2. 获取收益率统计
        _, _, _, stats, details = self.calculator.run_calculations()

        # 3. 绘制交互式HTML图表
        chart1_path = os.path.join(output_dir, f'{self.stock_name}_价格vs年线.html')
        chart2_path = os.path.join(output_dir, f'{self.stock_name}_年线乖离率.html')
        chart3_path = os.path.join(output_dir, f'{self.stock_name}_跌破年线持续天数.html')

        self.plot_chart1_html(save_path=chart1_path)
        self.plot_chart2_html(save_path=chart2_path)
        self.plot_chart3_html(save_path=chart3_path)

        # 4. 保存收益率统计结果
        if stats and details:
            stats_file = os.path.join(output_dir, f'{self.stock_name}_收益率统计.txt')
            with open(stats_file, 'w', encoding='utf-8') as f:
                f.write(f"{self.stock_name} 跌破年线买入收益率统计\n")
                f.write("="*60 + "\n\n")

                f.write("=== 总体统计 ===\n")
                f.write(f"样本数量: {stats['样本数量']}\n")
                f.write(f"60日平均收益率: {stats['60日平均收益率']}\n")
                f.write(f"60日收益率标准差: {stats['60日收益率标准差']}\n")
                f.write(f"120日平均收益率: {stats['120日平均收益率']}\n")
                f.write(f"120日收益率标准差: {stats['120日收益率标准差']}\n\n")

                f.write("=== 详细列表 ===\n")
                f.write(f"{'跌破日期':<15} {'买入价格':<12} {'60日后价格':<12} {'60日收益率':<15} {'120日后价格':<12} {'120日收益率':<15}\n")
                f.write("-"*90 + "\n")
                for detail in details:
                    f.write(f"{detail['跌破日期']:<15} {detail['买入价格']:<12} {detail['60日后价格']:<12} {detail['60日收益率']:<15} {detail['120日后价格']:<12} {detail['120日收益率']:<15}\n")

            print(f"\n收益率统计已保存至: {stats_file}")

        print("\n" + "="*60)
        print(f"分析完成！输出目录: {output_dir}")
        print("="*60)

        return True

    def plot_chart1_html(self, save_path=None):
        """
        绘制交互式HTML图表1：价格走势 vs 250日均线（含跌破区间标注）+ RSI 子图

        布局：2 行子图（shared_xaxes）+ 底部 rangeslider
        - 子图 1（上，65%）：价格 + MA250 + 跌破区间阴影
        - 子图 2（下，35%）：RSI6 / RSI12 / RSI24 + 70/30 辅助线
        - 底部 rangeslider：拖两个手柄精确选择时间范围（解决长周期下"鼠标抖动"问题）

        🆕 交互改进（解决"长周期数据下难以精确选中某一天"）：
        - rangeslider：底部迷你 slider，拖动手柄缩放
        - 细化 rangeselector：1周/1月/3月/6月/1年/3年/5年/全部
        - hoverdistance=8：悬停吸附更"粘"，减少抖动
        - dragmode='zoom'：明确启用拖拽框选缩放
        - spikedmode='across' + showspikes=True：十字线跨子图显示，精确定位

        操作说明（HTML 标题中也会显示）：
        - 鼠标滚轮：以光标为中心缩放
        - 拖拽空白：框选缩放
        - 双击：恢复初始视图
        - 拖底部 slider 手柄：精确选择时间范围
        - 点击图例：隐藏/显示该曲线

        参数：
        save_path: 保存路径，如果为None则显示图表
        """
        if self.df is None or 'MA250' not in self.df.columns:
            print("请先加载数据并计算")
            return

        print(f"\n正在绘制交互式HTML图表1: {self.stock_name} vs 250日均线走势 + RSI 指标")

        # 🆕 检查 RSI 列是否存在
        rsi_cols = [c for c in ['RSI6', 'RSI12', 'RSI24'] if c in self.df.columns]
        has_rsi = len(rsi_cols) > 0
        if not has_rsi:
            print("  ⚠️ 未检测到 RSI 列（RSI6/RSI12/RSI24），将仅绘制价格+MA250 子图")

        # 🆕 创建 2 行子图（若 RSI 不可用则回退为单图）
        if has_rsi:
            fig = make_subplots(
                rows=2, cols=1,
                shared_xaxes=True,
                vertical_spacing=0.08,
                row_heights=[0.6, 0.32],  # 🆕 留 8% 给底部 rangeslider
                subplot_titles=(
                    f'{self.stock_name} 价格 vs 250日均线',
                    'RSI 指标（6/12/24 三周期，鼠标悬停联动）',
                )
            )
            main_row = 1
            rsi_row = 2
        else:
            fig = go.Figure()
            main_row = 1
            rsi_row = None

        # 添加跌破年线区间的阴影标注（🆕 明确指定 row=main_row）
        for i, event in enumerate(self.break_events):
            break_date = event['break_date']
            recover_date = event['recover_date']

            # 获取该区间的价格范围
            mask = (self.df['日期'] >= break_date) & (self.df['日期'] <= recover_date)
            prices_in_range = self.df.loc[mask, '收盘'].values
            min_price = prices_in_range.min() if len(prices_in_range) > 0 else 0
            max_price = prices_in_range.max() if len(prices_in_range) > 0 else 0

            # 添加阴影矩形（仅加在主子图）
            fig.add_vrect(
                x0=break_date, x1=recover_date,
                y0=min_price, y1=max_price,
                fillcolor=COLOR_SHADE, opacity=0.3,
                layer="below", line_width=0,
                row=main_row, col=1,
            )

        # 添加价格线（深蓝色）到主子图
        fig.add_trace(go.Scatter(
            x=self.df['日期'],
            y=self.df['收盘'],
            mode='lines',
            name=f'{self.stock_name}价格走势',
            line=dict(color=COLOR_PRICE, width=1.5),
            hovertemplate='<b>%{x}</b><br>价格: %{y:.2f}<extra></extra>'
        ), row=main_row, col=1)

        # 添加250日均线（红色）到主子图
        fig.add_trace(go.Scatter(
            x=self.df['日期'],
            y=self.df['MA250'],
            mode='lines',
            name='250日均线',
            line=dict(color=COLOR_MA250, width=2),
            hovertemplate='<b>%{x}</b><br>MA250: %{y:.2f}<extra></extra>'
        ), row=main_row, col=1)

        # 🆕 添加 RSI 三周期到 RSI 子图
        rsi_colors = {
            'RSI6': '#FF1493',   # 深粉色（最敏感，醒目）
            'RSI12': '#4169E1',  # 皇家蓝（标准周期）
            'RSI24': '#2E8B57',  # 海洋绿（最平滑）
        }
        rsi_names = {
            'RSI6': 'RSI6（短线，券商标准）',
            'RSI12': 'RSI12（中短线，券商标准）',
            'RSI24': 'RSI24（中线，券商标准）',
        }

        if has_rsi:
            for col in rsi_cols:
                fig.add_trace(go.Scatter(
                    x=self.df['日期'],
                    y=self.df[col],
                    mode='lines',
                    name=rsi_names[col],
                    line=dict(color=rsi_colors[col], width=1.3),
                    hovertemplate=f'<b>%{{x}}</b><br>{rsi_names[col]}: %{{y:.2f}}<extra></extra>'
                ), row=rsi_row, col=1)

            # 70/30 超买超卖参考线（虚线）
            fig.add_hline(y=70, line_dash="dash", line_color="gray", line_width=1,
                          annotation_text="70 超买", annotation_position="top left",
                          row=rsi_row, col=1)
            fig.add_hline(y=30, line_dash="dash", line_color="gray", line_width=1,
                          annotation_text="30 超卖", annotation_position="bottom left",
                          row=rsi_row, col=1)
            # 50 中轴线（细实线）
            fig.add_hline(y=50, line_dash="dot", line_color="lightgray", line_width=1,
                          row=rsi_row, col=1)

            # 设置 RSI 子图 Y 轴范围
            fig.update_yaxes(title_text="RSI 值", range=[0, 100], row=rsi_row, col=1)

        # 设置主子图 Y 轴
        fig.update_yaxes(title_text="价格", row=main_row, col=1)

        # 设置 X 轴标题（最底行）
        if has_rsi:
            fig.update_xaxes(title_text="日期（拖底部 slider 选区，滚轮缩放，双击恢复）",
                             row=rsi_row, col=1)
        else:
            fig.update_xaxes(title_text="日期（拖底部 slider 选区，滚轮缩放，双击恢复）",
                             row=main_row, col=1)

        # 🆕 设置主子图 X 轴：rangeselector 按钮（细化到 1周/1月/3月/6月/1年/3年/5年/全部）
        fig.update_xaxes(
            rangeselector=dict(
                buttons=list([
                    dict(count=7, label="1周", step="day", stepmode="backward"),
                    dict(count=1, label="1月", step="month", stepmode="backward"),
                    dict(count=3, label="3月", step="month", stepmode="backward"),
                    dict(count=6, label="6月", step="month", stepmode="backward"),
                    dict(count=1, label="1年", step="year", stepmode="backward"),
                    dict(count=3, label="3年", step="year", stepmode="backward"),
                    dict(count=5, label="5年", step="year", stepmode="backward"),
                    dict(count=1, label="全部", step="all")
                ]),
                bgcolor='#E0E0E0',
                activecolor='#4169E1',
                font=dict(size=10),
            ),
            row=main_row, col=1,
        )

        # 🆕 全局布局：增加 hoverdistance、spike、dragmode
        layout_kwargs = dict(
            title=f'{self.stock_name} 价格 vs 250日均线 + RSI 指标（滚轮缩放 / 拖拽框选 / 底部 slider 选区）',
            hovermode='x unified',
            hoverdistance=8,  # 🆕 吸附 8 像素内最近点，减少抖动
            spikedistance=-1,  # 🆕 spike 总是吸附到最近数据点
            template='plotly_white',
            width=1400,
            height=1050 if has_rsi else 750,  # 🆕 增加 50px 容纳 rangeslider
            dragmode='zoom',  # 🆕 明确启用拖拽框选缩放（虽然 plotly 默认就是 zoom）
        )

        # 🆕 启用 spike（十字线跨子图显示）
        layout_kwargs['xaxis'] = dict(
            showspikes=True,
            spikethickness=1,
            spikedash='dot',
            spikecolor='#999999',
            spikesnap='cursor',
            spikemode='across',
            type="date",
        )
        if has_rsi:
            layout_kwargs['xaxis2'] = dict(
                showspikes=True,
                spikethickness=1,
                spikedash='dot',
                spikecolor='#999999',
                spikesnap='cursor',
                spikemode='across',
                # 🆕 在最底部子图加 rangeslider（plotly 要求 slider 绑定最后一个子图）
                rangeslider=dict(visible=True, thickness=0.04),
                type="date",
            )

        fig.update_layout(**layout_kwargs)

        if save_path:
            html_path = save_path.rsplit('.', 1)[0] + '.html'
            fig.write_html(html_path)
            print(f"  交互式HTML格式: {html_path}")
        else:
            fig.show()

    def plot_chart2_html(self, save_path=None):
        """
        绘制交互式HTML图表2：年线乖离率走势

        参数：
        save_path: 保存路径，如果为None则显示图表
        """
        if self.df is None or '乖离率' not in self.df.columns:
            print("请先加载数据并计算乖离率")
            return

        print(f"\n正在绘制交互式HTML图表2: {self.stock_name} 年线乖离率走势")

        # 创建图表
        fig = go.Figure()

        # 添加乖离率曲线（深蓝色）
        fig.add_trace(go.Scatter(
            x=self.df['日期'],
            y=self.df['乖离率'],
            mode='lines',
            name='年线乖离率',
            line=dict(color=COLOR_PRICE, width=1.5),
            hovertemplate='<b>%{x}</b><br>乖离率: %{y:.2f}%<extra></extra>'
        ))

        # 添加0基准线（黑色）
        fig.add_hline(
            y=0, line_dash="solid", line_color=COLOR_ZERO_AXIS, line_width=1.5
        )

        # 添加区域填充（高于年线为绿色，低于年线为红色）
        # 找到符号变化的点，将数据分成连续的同符号段
        segments = []
        current_segment = {'start_idx': 0, 'is_positive': None}

        for i in range(len(self.df)):
            current_val = self.df['乖离率'].iloc[i]
            is_positive = current_val >= 0

            # 如果是第一个点，或者符号发生了变化
            if i == 0:
                current_segment['is_positive'] = is_positive
            elif is_positive != current_segment['is_positive']:
                # 符号变化，保存当前段
                current_segment['end_idx'] = i - 1
                segments.append(current_segment.copy())

                # 开始新段
                current_segment = {'start_idx': i, 'is_positive': is_positive}

        # 添加最后一段
        current_segment['end_idx'] = len(self.df) - 1
        segments.append(current_segment)

        # 为每段创建单独的填充区域
        for i, segment in enumerate(segments):
            start_idx = segment['start_idx']
            end_idx = segment['end_idx']
            is_positive = segment['is_positive']

            # 提取该段的数据
            segment_dates = self.df['日期'].iloc[start_idx:end_idx+1]
            segment_values = self.df['乖离率'].iloc[start_idx:end_idx+1]

            # 为该段添加trace
            fig.add_trace(go.Scatter(
                x=segment_dates,
                y=segment_values,
                mode='none',
                fill='tozeroy',
                fillcolor=COLOR_POS_FILL if is_positive else COLOR_NEG_FILL,
                name='高于年线' if is_positive else '低于年线',
                hoverinfo='skip',
                showlegend=True if (i == 0 or (i == 1 and segments[0]['is_positive'] != is_positive)) else False
            ))

        # 设置布局
        fig.update_layout(
            title=f'{self.stock_name} 年线乖离率走势',
            xaxis_title='日期',
            yaxis_title='乖离率 (%)',
            hovermode='x unified',
            template='plotly_white',
            width=1400,
            height=700,
            xaxis=dict(
                rangeselector=dict(
                    buttons=list([
                        dict(count=1, label="1个月", step="month", stepmode="backward"),
                        dict(count=6, label="6个月", step="month", stepmode="backward"),
                        dict(count=1, label="1年", step="year", stepmode="backward"),
                        dict(count=1, label="全部", step="all")
                    ])
                ),
                rangeslider=dict(visible=True),
                type="date"
            )
        )

        if save_path:
            html_path = save_path.rsplit('.', 1)[0] + '.html'
            fig.write_html(html_path)
            print(f"  交互式HTML格式: {html_path}")
        else:
            fig.show()

    def plot_chart3_html(self, save_path=None):
        """
        绘制交互式HTML图表3：跌破年线持续交易日长度柱状图

        参数：
        save_path: 保存路径，如果为None则显示图表
        """
        if not self.break_events and not self.last_unfinished_break:
            print("没有跌破年线事件数据，无法绘制柱状图")
            return

        print(f"\n正在绘制交互式HTML图表3: {self.stock_name} 跌破年线持续交易日长度")

        # 准备数据
        event_labels = []
        durations = []
        colors = []  # 每个柱子的颜色
        is_finished = []  # 标记是否完成
        tooltips = []  # 鼠标悬停信息

        # 添加已完成的跌破事件
        for i, event in enumerate(self.break_events):
            break_date = event['break_date'].strftime('%Y-%m-%d')
            duration = event['recover_index'] - event['break_index']
            event_labels.append(break_date)
            durations.append(duration)
            colors.append(COLOR_NEG_FILL)  # 浅红色表示已完成
            is_finished.append(True)
            tooltips.append(f"跌破日期: {break_date}<br>持续天数: {duration}<br>状态: 已完成")
            print(f"  跌破事件{i+1}: {break_date}, 持续{duration}个交易日 (已完成)")

        # 添加未完成的跌破事件
        if self.last_unfinished_break:
            break_date = self.last_unfinished_break['break_date'].strftime('%Y-%m-%d')
            end_date = self.last_unfinished_break['end_date'].strftime('%Y-%m-%d')
            duration = self.last_unfinished_break['end_index'] - self.last_unfinished_break['break_index']
            event_labels.append(break_date)
            durations.append(duration)
            colors.append('#FFD700')  # 金黄色表示未完成
            is_finished.append(False)
            tooltips.append(f"跌破日期: {break_date}<br>持续天数: {duration}*<br>状态: 未完成<br>(截至{end_date})")
            print(f"  跌破事件(未完成): {break_date}, 截至{end_date}已持续{duration}个交易日 (未完成)")

        # 创建图表
        fig = go.Figure()

        # 分别绘制已完成和未完成的柱状图
        for i, (label, duration, color, finished, tooltip) in enumerate(zip(event_labels, durations, colors, is_finished, tooltips)):
            legend_group = '已完成跌破区间' if finished else '未完成跌破区间*'
            showlegend = (i == 0) or (not finished and i == len(self.break_events))

            fig.add_trace(go.Bar(
                x=[label],
                y=[duration],
                name=legend_group,
                marker=dict(color=color, line=dict(color=COLOR_PRICE, width=1.5)),
                hovertemplate=tooltip + '<extra></extra>',
                showlegend=showlegend,
                legendgroup=legend_group,
            ))

            # 在柱子上添加数值标注
            annotation_text = f'{int(duration)}*' if not finished else f'{int(duration)}'
            fig.add_annotation(
                x=label,
                y=duration,
                text=annotation_text,
                showarrow=False,
                yshift=5,
                font=dict(size=10)
            )

        # 设置布局
        fig.update_layout(
            title=f'{self.stock_name} 跌破年线持续交易日长度',
            xaxis_title='跌破年线日期',
            yaxis_title='持续交易日数',
            template='plotly_white',
            width=1400,
            height=700,
            barmode='group',
            xaxis=dict(tickangle=-45)
        )

        if save_path:
            html_path = save_path.rsplit('.', 1)[0] + '.html'
            fig.write_html(html_path)
            print(f"  交互式HTML格式: {html_path}")
        else:
            fig.show()


# ============ 主程序 ============
if __name__ == '__main__':
    import glob

    # 获取 data 目录下所有 CSV 文件
    csv_files = glob.glob('data/*.csv')

    if not csv_files:
        print("错误: data/ 目录下没有找到CSV文件")
    else:
        # 显示文件列表让用户选择
        print("="*60)
        print("请选择要分析的CSV文件:")
        print("="*60)
        for i, file in enumerate(csv_files, 1):
            print(f"{i}. {file}")

        print("="*60)
        choice = input("请输入文件编号(默认1): ").strip()

        # 默认选择第一个文件
        if not choice:
            choice = "1"

        try:
            file_index = int(choice) - 1
            if 0 <= file_index < len(csv_files):
                csv_file = csv_files[file_index]
                print(f"\n已选择文件: {csv_file}")
                print("="*60)

                analyzer = MA250Analyzer(csv_file)
                analyzer.run_analysis()
            else:
                print(f"错误: 无效的文件编号，请输入1-{len(csv_files)}之间的数字")
        except ValueError:
            print("错误: 请输入有效的数字编号")
