# -*- coding: utf-8 -*-
"""
将H30269perf.xlsx转换为512890格式的CSV文件
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
import sys

def convert_excel_to_csv(excel_file='data/H30269perf.xlsx', output_file='data/H20269历史数据.csv'):
    """
    转换Excel文件为CSV格式

    参数：
    excel_file: 输入的Excel文件名
    output_file: 输出的CSV文件名
    """

    print(f"正在读取Excel文件: {excel_file}")

    # 读取Excel文件
    df = pd.read_excel(excel_file)

    print(f"原始数据形状: {df.shape}")
    print(f"原始列名: {df.columns.tolist()}")

    # 只选择H20269指数的数据（包含完整的OHLC数据）
    df = df[df['指数代码Index Code'] == 'H20269'].copy()
    print(f"筛选H20269后的数据形状: {df.shape}")

    # 列名映射（从中英文混合列名映射到目标格式）
    column_mapping = {
        '日期Date': '日期',
        '收盘Close': '收盘',
        '开盘Open': '开盘',
        '最高High': '高',
        '最低Low': '低',
        '成交量 Volume': '交易量',
        '涨跌幅(%)Change(%)': '涨跌幅'
    }

    # 选择并重命名列
    df_selected = df[list(column_mapping.keys())].copy()
    df_selected.rename(columns=column_mapping, inplace=True)

    # 格式化日期：从20130701转换为2013-07-01
    df_selected['日期'] = pd.to_datetime(df_selected['日期'], format='%Y%m%d')
    df_selected['日期'] = df_selected['日期'].dt.strftime('%Y-%m-%d')

    # 格式化涨跌幅：添加百分号
    # 检查涨跌幅列，如果已经是百分数格式，则添加%符号
    df_selected['涨跌幅'] = df_selected['涨跌幅'].apply(lambda x: f"{x:.2f}%" if pd.notna(x) else "")

    # 按日期升序排序（确保数据从旧到新）
    df_selected = df_selected.sort_values('日期')

    # 重置索引
    df_selected = df_selected.reset_index(drop=True)

    # 保存为CSV文件（使用utf-8-sig编码以确保Excel能正确打开）
    df_selected.to_csv(output_file, index=False, encoding='utf-8-sig')

    print(f"\n转换完成！")
    print(f"输出文件: {output_file}")
    print(f"数据行数: {len(df_selected)}")
    print(f"\n前5行预览:")
    print(df_selected.head().to_string())
    print(f"\n最后5行预览:")
    print(df_selected.tail().to_string())

    return df_selected

if __name__ == '__main__':
    # 设置stdout编码为utf-8
    sys.stdout.reconfigure(encoding='utf-8')

    # 执行转换
    convert_excel_to_csv()

    print("\n转换脚本执行完成！")
    print("现在可以使用 analyze_ma250.py 分析H30269的历史走势了。")
