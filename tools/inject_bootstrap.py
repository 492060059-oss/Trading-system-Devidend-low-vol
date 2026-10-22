# -*- coding: utf-8 -*-
"""给重构后的脚本注入「项目根引导」前言

重构把代码分到 core/ scripts/ tools/ 三层后，脚本需要：
  1) 把项目根与 core/ 挂到 sys.path（否则 `from data_calculator import ...` 失败）
  2) 把工作目录切到项目根（否则 'data/xxx.csv' 这类相对路径失效）

本脚本在每个目标文件的【首个 import 之前】插入一段自包含前言。
之所以不写成 `import _bootstrap`，是因为那本身就需要项目根已在 sys.path 上
—— 鸡生蛋问题。所以前言必须自己先定位项目根。

幂等：已注入的文件会跳过。
"""
import os
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 本文件在 tools/ 下

MARK = '# === PROJECT-ROOT BOOTSTRAP ==='

PRELUDE = '''{mark}
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

'''.format(mark=MARK)

TARGETS = ([os.path.join('scripts', f) for f in [
    'run_multiple_backtests.py', 'run_extended_backtests.py',
    'run_512890_backtests.py', 'regenerate_charts.py',
    'generate_rsi_report.py', 'convert_excel_to_csv.py']]
    + [os.path.join('tools', 'audit_checks.py')]
    + [os.path.join('core', f) for f in [
        'rolling_position_backtest.py', 'performance_analysis.py',
        'analyze_ma250.py', 'data_calculator.py']])


def find_insert_pos(lines):
    """返回应插入的行号：跳过 shebang、编码声明、模块 docstring 与文件头注释"""
    i = 0
    n = len(lines)
    # shebang / 编码声明
    while i < n and (lines[i].startswith('#!') or 'coding' in lines[i][:40]):
        i += 1
    # 模块 docstring
    while i < n and not lines[i].strip():
        i += 1
    if i < n:
        st = lines[i].lstrip()
        for q in ('"""', "'''"):
            if st.startswith(q):
                # 单行 docstring？
                if st.count(q) >= 2 and len(st.strip()) > len(q):
                    i += 1
                else:
                    i += 1
                    while i < n and q not in lines[i]:
                        i += 1
                    i += 1
                break
    return i


added = skipped = 0
for rel in TARGETS:
    p = os.path.join(ROOT, rel)
    if not os.path.exists(p):
        print(f'  [MISS] {rel}')
        continue
    src = open(p, encoding='utf-8').read()
    if MARK in src:
        print(f'  [SKIP] {rel}  (已注入)')
        skipped += 1
        continue
    lines = src.split('\n')
    pos = find_insert_pos(lines)
    new = '\n'.join(lines[:pos]) + '\n' + PRELUDE + '\n'.join(lines[pos:])
    open(p, 'w', encoding='utf-8').write(new)
    print(f'  [ADD ] {rel}  (插入到第 {pos + 1} 行)')
    added += 1

print(f'\n注入 {added} 个，跳过 {skipped} 个')

# 语法校验
import py_compile
bad = 0
for rel in TARGETS:
    p = os.path.join(ROOT, rel)
    if not os.path.exists(p):
        continue
    try:
        py_compile.compile(p, doraise=True)
    except Exception as e:
        print(f'  [SYNTAX FAIL] {rel}: {e}')
        bad += 1
print('语法校验：' + ('全部通过' if bad == 0 else f'{bad} 个失败'))
