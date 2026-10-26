# -*- coding: utf-8 -*-
"""
看板实时渲染：现场拉取最新数据 → 复用 build_dashboard 渲染 HTML。

与静态流程（update_data.py 落盘 + build_dashboard.py 读盘）不同，本模块不落盘，
每次调用直接联网取数并计算，供 dashboard_app.py（Web 服务，Render 免费实例部署）
调用。数据链路有三层兜底：

    H20269:  中证官网API(拉约5年) -> 仓库 data/H20269历史数据.csv
    512890:  东财前复权 -> 腾讯分段 -> 仓库 data/512890行情数据.csv

结果缓存 10 分钟（TTL），避免频繁刷新打爆数据源。
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

import time

import pandas as pd

import build_dashboard as bd   # noqa: E402  (scripts/ 已由调用方挂入 sys.path)
import update_data as ud       # noqa: E402

# 拉约 5 年半：MA250 需 250 日 + RSI(Wilder ewm) 预热收敛 + 近2年图表窗口，足够
HISTORY_START = '20210101'
CACHE_TTL = 600  # 秒

_cache = {'html': None, 'ts': 0.0}


def fetch_h20269_live():
    """中证官网 API，返回 DataFrame(日期, 收盘)。"""
    end = ud.beijing_now().strftime('%Y%m%d')
    url = ('https://www.csindex.com.cn/csindex-home/perf/index-perf'
           f'?indexCode=H20269&startDate={HISTORY_START}&endDate={end}')
    payload = ud.fetch_json(url, headers={'Referer': 'https://www.csindex.com.cn/'})
    rows = payload.get('data') or []
    if len(rows) < 300:
        raise RuntimeError(f'csindex 返回行数异常: {len(rows)}')
    df = pd.DataFrame({
        '日期': pd.to_datetime([r['tradeDate'] for r in rows]),
        '收盘': [float(r['close']) for r in rows],
    })
    return df.sort_values('日期').reset_index(drop=True)


def fetch_etf_live():
    """东财 -> 腾讯 两级兜底，返回 DataFrame(日期, 收盘)。"""
    last_err = None
    for fn in (ud.fetch_etf_eastmoney, ud.fetch_etf_tencent):
        try:
            recs = fn()
            df = pd.DataFrame({'日期': pd.to_datetime([r[0] for r in recs]),
                               '收盘': [r[1] for r in recs]})
            return df.sort_values('日期').reset_index(drop=True)
        except Exception as e:
            last_err = e
    raise last_err


def _load_csv(path):
    df = pd.read_csv(path, encoding='utf-8-sig')
    df['日期'] = pd.to_datetime(df['日期'])
    return df[['日期', '收盘']]


def get_dashboard_html(force=False):
    """实时渲染看板 HTML（带 10 分钟缓存）。API 全挂时退回仓库 CSV。"""
    if not force and _cache['html'] and time.time() - _cache['ts'] < CACHE_TTL:
        return _cache['html']

    notes = []
    try:
        idx_raw = fetch_h20269_live()
    except Exception:
        idx_raw = _load_csv('data/H20269历史数据.csv')
        notes.append('H20269 实时源暂不可用，已退回仓库缓存')
    try:
        etf_raw = fetch_etf_live()
    except Exception:
        etf_raw = _load_csv('data/512890行情数据.csv')
        notes.append('512890 实时源暂不可用，已退回仓库缓存')

    idx = bd.compute_indicators(idx_raw)
    etf = bd.compute_indicators(etf_raw)
    html = bd.assemble_html(idx, etf, source_note='；'.join(notes))
    _cache.update(html=html, ts=time.time())
    return html


if __name__ == '__main__':
    print(get_dashboard_html(force=True)[:400])
