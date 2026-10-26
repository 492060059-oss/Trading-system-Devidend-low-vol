# -*- coding: utf-8 -*-
"""
每日数据自动更新：无需再从中证指数官网手动下载

数据源（均免费、无需鉴权，2026-10-23 实测验证）：
1. H20269 红利低波全收益指数 —— 中证指数官网 API
   https://www.csindex.com.cn/csindex-home/perf/index-perf
   参数 indexCode/startDate/endDate（注意不是 startDt/endDt）。
   与本地 data/H20269历史数据.csv 重叠 287 天收盘价零差异，故采用【只追加】
   策略：历史字节原样保留，仅追加新日期行，保证既有回测结果可精确复现。
   注意：官网 autofile 路径（H30269perf.xls）2024-11 后已停更，勿再使用。
2. 512890 红利低波ETF —— 东方财富 kline API（主）+ 腾讯行情 API（备）
   前复权口径，与本地手工导出的 512890历史数据.csv 一致（±0.001 舍入差）。
   写入独立文件 data/512890行情数据.csv（每次全量刷新）；回测用的
   data/512890历史数据.csv 保持不动，以免破坏旧回测的复现性。

用法：
    python scripts/data/update_data.py          # 更新两个文件
    python scripts/data/update_data.py --check  # 只查看数据新旧，不写任何文件

本地可挂 Windows 计划任务每日运行；GitHub Actions 中由
.github/workflows/update-data.yml 定时调用。
"""
# === PROJECT-ROOT BOOTSTRAP ===
# 重构后代码分层（core/ scripts/ tools/），此前言保证脚本从任何目录调用都可用：
# 把项目根与 core/ 挂上 sys.path，并将工作目录切到项目根，
# 使代码中所有 'data/...'、'output/...' 相对路径继续生效（无需逐个改写）。
import os as _os
import sys as _sys
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
for _p in (_ROOT, _os.path.join(_ROOT, 'core')):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)
if _os.path.abspath(_os.getcwd()) != _ROOT:
    _os.chdir(_ROOT)
# === /PROJECT-ROOT BOOTSTRAP ===

import json
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone

if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

H20269_CSV = 'data/H20269历史数据.csv'
ETF_CSV = 'data/512890行情数据.csv'   # 留档/看板副项目用；回测的 512890历史数据.csv 不动
ETF_CODE = '512890'

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/126.0 Safari/537.36')


def fetch_json(url, headers=None, retries=3, timeout=30):
    """带重试的 GET JSON。"""
    hdrs = {'User-Agent': UA}
    if headers:
        hdrs.update(headers)
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except Exception as e:  # 网络抖动/限流：退避后重试
            last_err = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f'请求失败（已重试{retries}次）: {url} -> {last_err}')


def beijing_now():
    return datetime.now(timezone(timedelta(hours=8)))


# ---------------------------------------------------------------- H20269 ----

def update_h20269(check_only=False):
    """中证官网 API 增量追加。返回 (旧末行日期, 新末行日期, 追加行数)。"""
    with open(H20269_CSV, encoding='utf-8-sig') as f:
        lines = f.read().splitlines()
    # 找最后一行日期（跳过空行）
    data_lines = [ln for ln in lines if ln.strip()]
    if len(data_lines) < 2:
        raise RuntimeError(f'{H20269_CSV} 内容异常')
    last_date_str = data_lines[-1].split(',')[0]
    last_date = datetime.strptime(last_date_str, '%Y-%m-%d')
    print(f'[H20269] 本地末行: {last_date_str}（共 {len(data_lines)-1} 个交易日）')

    start = (last_date + timedelta(days=1)).strftime('%Y%m%d')
    end = beijing_now().strftime('%Y%m%d')
    url = ('https://www.csindex.com.cn/csindex-home/perf/index-perf'
           f'?indexCode=H20269&startDate={start}&endDate={end}')
    payload = fetch_json(url, headers={'Referer': 'https://www.csindex.com.cn/'})
    rows = payload.get('data') or []
    rows.sort(key=lambda r: r['tradeDate'])
    print(f'[H20269] 官网API返回 {len(rows)} 行（{start}~{end}）')

    if not rows:
        print('[H20269] 无新数据（当日尚未发布或已是最新）')
        return last_date_str, last_date_str, 0
    if rows[0]['tradeDate'] <= last_date.strftime('%Y%m%d'):
        raise RuntimeError(f'API 返回了不晚于本地末行的日期 {rows[0]["tradeDate"]}，拒绝追加')

    new_lines = []
    prev_close = None
    for r in rows:
        d = datetime.strptime(r['tradeDate'], '%Y%m%d')
        close = float(r['close'])
        # 涨跌幅缺失时用前后收盘价补算
        pct = r.get('changePct')
        if pct is None:
            pct = (close / prev_close - 1) * 100 if prev_close else None
        prev_close = close
        vol = float(r.get('tradingVol') or 0)
        parts = [d.strftime('%Y-%m-%d'), f'{close:.2f}']
        for k in ('open', 'high', 'low'):
            v = r.get(k)
            parts.append(f'{float(v):.2f}' if v is not None else '')
        parts.append(f'{vol:.1f}')
        parts.append(f'{float(pct):.2f}%' if pct is not None else '')
        new_lines.append(','.join(parts))

    if check_only:
        print(f'[H20269] --check 模式：将追加 {len(new_lines)} 行（至 {rows[-1]["tradeDate"]}），未写入')
        return last_date_str, rows[-1]['tradeDate'], len(new_lines)

    with open(H20269_CSV, 'a', encoding='utf-8-sig', newline='') as f:
        # 原文件若不以换行结尾，先补一个（utf-8-sig 的 BOM 只在文件头出现一次）
        need_nl = not lines[-1] == '' if lines else True
        if need_nl and lines and lines[-1].strip():
            f.write('\n')
        f.write('\n'.join(new_lines) + '\n')
    new_last = rows[-1]['tradeDate']
    print(f'[H20269] 已追加 {len(new_lines)} 行 -> 末行 {new_last}')
    return last_date_str, new_last, len(new_lines)


# ---------------------------------------------------------------- 512890 ----

def fetch_etf_eastmoney():
    """东财 kline：一次请求全量前复权日线。返回 DataFrame(日期str, 收盘, 成交量手)。"""
    url = ('https://push2his.eastmoney.com/api/qt/stock/kline/get'
           '?secid=1.512890&fields1=f1,f2,f3&fields2=f51,f53,f56'
           '&klt=101&fqt=1&lmt=3000&end=20500101')
    data = fetch_json(url).get('data') or {}
    klines = data.get('klines') or []
    if len(klines) < 1500:
        raise RuntimeError(f'东财返回行数异常: {len(klines)}')
    recs = []
    for k in klines:
        p = k.split(',')
        recs.append((p[0], float(p[1]), float(p[2]) if len(p) > 2 else 0.0))
    return recs


def fetch_etf_tencent():
    """腾讯行情：单次上限约 640 行，按时间窗分段后合并（东财故障时的备份源）。"""
    windows = [('2019-01-01', '2021-12-31'), ('2022-01-01', '2023-12-31'),
               ('2024-01-01', '2024-12-31'), ('2025-01-01', '2026-12-31')]
    recs, seen = [], set()
    for s, e in windows:
        url = (f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get'
               f'?param=sh{ETF_CODE},day,{s},{e},640,qfq')
        payload = fetch_json(url, headers={'Referer': 'https://gu.qq.com/'})
        node = payload['data'][f'sh{ETF_CODE}']
        rows = node.get('qfqday') or node.get('day') or []
        for r in rows:  # r = [日期, 开, 收, 高, 低, 量, ...]
            if r[0] not in seen:
                seen.add(r[0])
                recs.append((r[0], float(r[2]), float(r[5]) if len(r) > 5 else 0.0))
    recs.sort(key=lambda x: x[0])
    if len(recs) < 1500:
        raise RuntimeError(f'腾讯合并后行数异常: {len(recs)}')
    return recs


def update_etf(check_only=False):
    """全量刷新 ETF 前复权序列（留档/看板副项目用）。"""
    source = 'eastmoney'
    try:
        recs = fetch_etf_eastmoney()
    except Exception as e:
        print(f'[512890] 东财失败（{e}），改用腾讯备份源')
        source = 'tencent'
        recs = fetch_etf_tencent()
    print(f'[512890] {source} 返回 {len(recs)} 行: {recs[0][0]} ~ {recs[-1][0]}')

    # 一致性校验：日期严格升序、无重复
    dates = [r[0] for r in recs]
    if dates != sorted(dates) or len(set(dates)) != len(dates):
        raise RuntimeError('日期非升序或存在重复，拒绝写入')

    out_lines = ['日期,收盘,开盘,高,低,交易量,涨跌幅']
    prev_close = None
    for d, close, vol in recs:
        pct = (close / prev_close - 1) * 100 if prev_close else None
        prev_close = close
        # 与 512890历史数据.csv 同构；开高低未知列留空（只用日期/收盘）
        out_lines.append(f'{d},{close:.3f},,,,{vol:.1f},'
                         + (f'{pct:.2f}%' if pct is not None else ''))

    if check_only:
        print(f'[512890] --check 模式：将全量刷新 {len(recs)} 行，未写入')
        return recs[-1][0], 0

    with open(ETF_CSV, 'w', encoding='utf-8-sig', newline='') as f:
        f.write('\n'.join(out_lines) + '\n')
    print(f'[512890] 已写入 {ETF_CSV}（{len(recs)} 行，末行 {recs[-1][0]}，来源 {source}）')
    return recs[-1][0], len(recs)


def main():
    check_only = '--check' in sys.argv
    print(f'运行时间（北京时间）: {beijing_now().strftime("%Y-%m-%d %H:%M:%S")}'
          + ('  [--check 只读模式]' if check_only else ''))
    ok = {}
    try:
        ok['H20269'] = update_h20269(check_only)
    except Exception as e:
        print(f'[H20269] 更新失败: {e}')
    try:
        ok['512890'] = update_etf(check_only)
    except Exception as e:
        print(f'[512890] 更新失败: {e}')
    if not ok:
        raise SystemExit('两个标的均更新失败，请检查网络')
    print('完成。')


if __name__ == '__main__':
    main()
