# 项目整理方案

## 最后更新时间
2026-08-23（✅ **方案 C 已执行完毕**，见文末「执行记录」）

## 文档定位

✅ **本方案已于 2026-08-23 执行**（用户选定「方案 C + 补充新文件」）。

本文档保留为**决策与执行记录**：正文的方案设计部分维持原样（记录当时的
权衡），实际执行时与原方案的**偏离之处记在文末「执行记录」**。

> ⚠️ 正文 1.1 节的文件清单写于 2026-08-05，**已过期**：其后新增了
> `tools/audit_checks.py`、`tools/ab_compare/` 工具链等文件，原清单未包含。
> **当前真实结构请看项目根的 `README.md`。**

---

## 一、当前结构问题诊断

### 1.1 根目录文件清单（截至 2026-08-05）

```
红利低波价格走势分析程序/
│
├── __pycache__/                        # Python 缓存（应忽略）
│
├── 【核心代码 4 个】
│   ├── data_calculator.py              # 数据计算（基础模块）
│   ├── rolling_position_backtest.py    # 滚动仓位回测（主策略）
│   ├── performance_analysis.py         # 策略表现时间维度分析
│   └── analyze_ma250.py                # MA250 可视化（含 RSI 子图）
│
├── 【工具脚本 5 个】
│   ├── convert_excel_to_csv.py         # Excel→CSV 转换
│   ├── run_multiple_backtests.py       # 多起始日批量回测
│   ├── run_extended_backtests.py       # 扩展回测（14 起始日）
│   ├── run_512890_backtests.py         # 512890 ETF 回测
│   └── regenerate_charts.py            # 重新生成图表
│
├── 【专题分析 1 个】
│   └── generate_rsi_report.py          # 🆕 RSI 止盈决策报告生成器
│
├── 【文档 5 个】
│   ├── progress.md                     # 进度记录
│   ├── ANALYZE_MA250_GUIDE.md          # MA250 工具使用指南
│   ├── RSI_ANALYSIS_FRAMEWORK.md       # RSI 框架设计
│   ├── ROLLING_POSITION_STRATEGY.md    # 滚动仓位策略详细规则
│   └── STRATEGY_DESIGN.md              # 原策略设计（已暂停）
│
├── 【新增 1 个】
│   └── PROJECT_REORGANIZATION_PLAN.md  # 本文档
│
├── data/                               # 数据文件夹
│   ├── H30269perf.xlsx                 # 原始中证下载
│   ├── H20269历史数据.csv              # 主标的（5001 条）
│   ├── H30269历史数据.csv              # 价格指数（备用）
│   ├── 512890历史数据.csv              # ETF 数据
│   └── 515450历史数据.csv              # ETF 数据（备用）
│
└── output/                             # 所有输出
    ├── analysis_output/                # analyze_ma250 输出（4 个 HTML）
    ├── reports/                        # 🆕 专题分析报告
    │   ├── H20269_RSI止盈决策分析报告_2026-08-04.html
    │   └── H20269_RSI止盈决策分析报告_2026-08-04.md
    ├── rolling_output_*/               # 17 个回测结果目录
    ├── 跨起始日对比.html / .md          # 汇总
    ├── H20269_扩展测试汇总.html / .md   # 汇总
    └── 512890_ETF跟踪能力测试汇总.html / .md
```

### 1.2 三大痛点

| 痛点 | 表现 | 影响 |
|------|------|------|
| **核心 vs 工具混杂** | 9 个 .py 文件混杂在根目录 | 阅读者不知道哪个是核心、哪个是一次性脚本 |
| **文档分散** | 5 个 .md 文件与代码混杂 | 文档查找困难，新人入门不友好 |
| **output/ 过度扁平** | 17 个 rolling_output_* + 多个汇总直接堆叠 | 浏览成本高，新旧结果难区分 |

---

## 二、整理方案对比

### 方案 A：彻底重组（推荐用于长期维护）

按"功能分层"组织，所有文件按 `src/` / `scripts/` / `docs/` 分类。

**优点**：结构清晰，专业感强，类似开源项目
**缺点**：需要改 import 路径（`from data_calculator` → `from src.data_calculator`），改动量大

### 方案 B：轻量整理（推荐用于个人研究）

只整理最乱的 `output/` 和 `docs/`，代码保持原位。

**优点**：风险小，改动少
**缺点**：根目录仍有代码混杂

### 方案 C：折中整理（最推荐）⭐

代码按"核心 vs 工具"二级分类，文档集中，output 整理。

**优点**：改善最痛点，import 改动最小（用 sys.path 或保持原位）
**缺点**：仍有少量代码混杂

---

## 三、推荐方案 C 详细设计

### 3.1 目标结构

```
红利低波价格走势分析程序/
│
├── 📁 core/                                # 核心代码（可复用模块）
│   ├── data_calculator.py                  # 数据计算（基础模块）
│   ├── rolling_position_backtest.py        # 滚动仓位回测（主策略）
│   ├── performance_analysis.py             # 策略表现分析
│   └── analyze_ma250.py                    # MA250 可视化模块
│
├── 📁 scripts/                             # 工具脚本（一次性运行）
│   ├── convert_excel_to_csv.py             # Excel→CSV 转换
│   ├── run_multiple_backtests.py           # 多起始日批量回测
│   ├── run_extended_backtests.py           # 扩展回测
│   ├── run_512890_backtests.py             # 512890 ETF 回测
│   ├── regenerate_charts.py                # 重新生成图表
│   └── generate_rsi_report.py              # RSI 报告生成器
│
├── 📁 docs/                                # 所有文档
│   ├── progress.md                         # 进度记录
│   ├── ANALYZE_MA250_GUIDE.md              # MA250 工具指南
│   ├── RSI_ANALYSIS_FRAMEWORK.md           # RSI 框架设计
│   ├── ROLLING_POSITION_STRATEGY.md        # 策略详细规则
│   ├── STRATEGY_DESIGN.md                  # 原策略设计（暂停）
│   └── PROJECT_REORGANIZATION_PLAN.md      # 本文档
│
├── 📁 data/                                # 数据（保持原位）
│   ├── H30269perf.xlsx                     # 原始下载
│   ├── H20269历史数据.csv                  # 主标的
│   └── etf/                                # 可选：ETF 子目录
│       ├── 512890历史数据.csv
│       └── 515450历史数据.csv
│
├── 📁 output/                              # 所有输出（二级分类）
│   ├── analysis/                           # analyze_ma250 输出
│   │   └── (4 个 HTML)
│   ├── backtests/                          # 回测结果（三级分类）
│   │   ├── h20269/                         # H20269 回测（17 个 → 按起始日命名）
│   │   │   ├── 2015-05起_深度定投策略/
│   │   │   ├── 2016-01起_深度定投策略/
│   │   │   └── ...
│   │   ├── etf512890/                      # 512890 ETF 回测
│   │   │   └── ...
│   │   └── comparisons/                    # 跨起始日对比
│   │       ├── 跨起始日对比.html
│   │       ├── 跨起始日对比汇总.md
│   │       ├── H20269_扩展测试汇总.html
│   │       └── 512890_ETF跟踪能力测试汇总.md
│   └── reports/                            # 专题分析报告
│       ├── H20269_RSI止盈决策分析报告_2026-08-04.html
│       └── H20269_RSI止盈决策分析报告_2026-08-04.md
│
├── README.md                               # 项目总览（新增）
├── .gitignore                              # 忽略 __pycache__ 等（新增）
└── requirements.txt                        # 依赖列表（新增）
```

### 3.2 各文件作用详解

#### `core/` - 核心代码（4 个）

| 文件 | 作用 | 依赖关系 |
|------|------|---------|
| `data_calculator.py` | 基础数据计算（MA250/乖离率/RSI/跌破事件） | 无（被所有其他模块引用） |
| `rolling_position_backtest.py` | MA250 长线策略回测（主策略） | 依赖 `data_calculator` |
| `performance_analysis.py` | 策略表现时间维度分析（9 阶段切分） | 依赖 `rolling_position_backtest` 的输出 |
| `analyze_ma250.py` | MA250 可视化（含 RSI 子图） | 依赖 `data_calculator` |

#### `scripts/` - 工具脚本（6 个）

| 文件 | 作用 | 何时运行 |
|------|------|---------|
| `convert_excel_to_csv.py` | 把中证下载的 xlsx 转 CSV | 数据更新时 |
| `run_multiple_backtests.py` | 批量跑多起始日回测 | 验证稳健性时 |
| `run_extended_backtests.py` | 扩展回测 10 个新起始日 | 大规模稳健性验证 |
| `run_512890_backtests.py` | 512890 ETF 5 个起始日回测 | ETF 跟踪能力测试 |
| `regenerate_charts.py` | 重新生成所有 HTML 图表 | 图表逻辑修改后 |
| `generate_rsi_report.py` | 生成 RSI 专题分析报告 | 专题分析时 |

#### `docs/` - 文档（6 个）

| 文件 | 作用 | 阅读对象 |
|------|------|---------|
| `progress.md` | 项目所有变更滚动时间线 | 维护者 |
| `ANALYZE_MA250_GUIDE.md` | analyze_ma250 使用指南 | 新人/用户 |
| `RSI_ANALYSIS_FRAMEWORK.md` | RSI 框架设计（待实施） | 策略设计者 |
| `ROLLING_POSITION_STRATEGY.md` | 滚动仓位策略详细规则 | 策略审核者 |
| `STRATEGY_DESIGN.md` | 原策略设计（已暂停，参考用） | 历史查阅 |
| `PROJECT_REORGANIZATION_PLAN.md` | 本文档 | 整理执行者 |

---

## 四、实施步骤（如果决定执行）

### Step 1：创建目录结构

```bash
mkdir -p core scripts docs output/analysis output/backtests/h20269
mkdir -p output/backtests/etf512890 output/backtests/comparisons
```

### Step 2：移动文件

```bash
# 核心代码
mv data_calculator.py rolling_position_backtest.py performance_analysis.py analyze_ma250.py core/

# 工具脚本
mv convert_excel_to_csv.py run_*.py regenerate_charts.py generate_rsi_report.py scripts/

# 文档
mv progress.md *_GUIDE.md *_FRAMEWORK.md *_STRATEGY.md *_DESIGN.md PROJECT_*.md docs/

# 输出二级分类
mv output/analysis_output/* output/analysis/
mv output/reports output/reports  # 已就位

# 回测结果三级分类
mv output/rolling_output_2015-05起_* output/rolling_output_2016-* output/backtests/h20269/
mv output/rolling_output_512890_* output/backtests/etf512890/
mv output/rolling_output_H20269_* output/backtests/h20269/
mv output/跨起始日* output/H20269_扩展* output/512890_* output/backtests/comparisons/
```

### Step 3：修复 import 路径

由于 `core/` 和 `scripts/` 分离，`scripts/` 中的脚本需要：

**选项 A（推荐）**：在每个 script 开头加：
```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'core'))
```

**选项 B**：在 `core/` 中创建 `__init__.py`，改为包导入：
```python
from core.data_calculator import MA250DataCalculator
```

### Step 4：修复路径引用

代码中所有硬编码路径需要调整：
- `'data/H20269历史数据.csv'` → `'../data/H20269历史数据.csv'`（如果在 scripts/ 中）
- `'output/rolling_output'` → `'../output/backtests/h20269/'`

### Step 5：创建配套文件

#### `README.md`（项目总览）
- 项目简介
- 快速开始
- 文件结构说明
- 主要文档链接

#### `.gitignore`
```
__pycache__/
*.pyc
.DS_Store
output/**/*.csv  # 不提交大文件
data/*.xlsx      # 不提交原始数据
```

#### `requirements.txt`
```
pandas>=1.5.0
numpy>=1.21.0
plotly>=5.0.0
matplotlib>=3.5.0
openpyxl>=3.0.0
```

### Step 6：验证

- 运行 `python scripts/convert_excel_to_csv.py` 验证数据转换
- 运行 `python scripts/generate_rsi_report.py` 验证报告生成
- 运行 `python core/rolling_position_backtest.py` 验证主策略

---

## 五、风险评估

### 5.1 主要风险

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| import 路径漏改 | 中 | 脚本运行失败 | 完整测试每个脚本 |
| 硬编码路径漏改 | 中 | 输出文件丢失 | grep 全文搜索 'output/' |
| 文档中的相对路径失效 | 低 | 链接 404 | grep 全文搜索 'output/rolling' |
| 现有回测结果路径引用断 | 低 | 旧报告引用失效 | 在 progress.md 记录路径变更 |

### 5.2 回滚方案

如果整理后出现问题，可以快速回滚：
- 整理前 git commit（如有 git）
- 或备份整个目录到 `_backup_2026-08-05/`

---

## 六、不整理的成本

如果不整理，长期问题：
- 新增脚本时不知道放哪
- 文档查找耗时
- 现有 9 个 .py + 5 个 .md + 17 个 output 子目录 会继续膨胀
- 新人入门门槛越来越高

---

## 七、决策建议

**建议执行方案 C（折中整理）**，理由：

1. 改善最痛点（output 杂乱、文档分散）
2. import 改动最小（用 sys.path 注入）
3. 保留所有现有功能
4. 历史结果路径变化但有 progress.md 记录

**不推荐方案 A**，理由：
- 需要改 import 路径为包导入（`from core.data_calculator import ...`）
- 工作量大，且对个人研究项目收益有限

**等待用户指令**：审核本方案后，告知执行哪个方案。

---

## 八、执行记录（2026-08-23）

用户指令：「PROJECT_REORGANIZATION_PLAN 中提到了对项目进行重构整理，
目前项目太乱了，需要重新整理。」并选定 **方案 C + 补充新文件**。

### 8.1 实际执行的步骤

| Step | 状态 | 说明 |
|------|------|------|
| 0. 备份 | ✅ | `../_backup_红利低波_2026-08-23/`（268 MB）。**本项目不是 git 仓库，无回滚能力**，故必须先备份 |
| 1. 创建目录 | ✅ | `core/ scripts/ tools/ab_compare/ docs/ output/{backtests/{h20269,etf512890,comparisons},analysis,reports}` |
| 2. 移动文件 | ✅ | 4 核心模块 → `core/`；7 脚本 → `scripts/`；`audit_checks.py` + `ab_compare/` → `tools/`；6 文档 → `docs/` |
| 3. 修复 import | ✅ | 见 8.2（**未采用原方案的 Step 3 选项 A**） |
| 4. 修复路径引用 | ✅ | 见 8.3（**未采用原方案的 Step 4 做法**） |
| 5. 配套文件 | ✅ | `README.md`、`.gitignore`、`requirements.txt` |
| 6. 验证 | ✅ | 见 8.4 |

### 8.2 偏离原方案：import 修复用「引导前言」而非选项 A

原 Step 3 选项 A 只把 `core/` 挂到 `sys.path`，**不解决工作目录问题** ——
代码里还有约 30 处 `'data/...'`、`'output/...'` 相对路径，从 `scripts/`
调用时全部失效。

实际做法：`tools/inject_bootstrap.py` 给 11 个文件顶部注入一段自包含前言
（`# === PROJECT-ROOT BOOTSTRAP ===`），同时做两件事：

1. 把项目根与 `core/` 插入 `sys.path`
2. `os.chdir(项目根)`

好处是**所有相对路径原样有效**，且脚本可从任意目录调用。

> 为什么不写成 `import _bootstrap`？因为那本身就要求项目根已在 `sys.path`
> 上 —— 鸡生蛋。前言必须自己先定位项目根。（曾创建过 `_bootstrap.py`，
> 因此已删除。）

### 8.3 偏离原方案：不改成 `../data/...`

原 Step 4 建议把路径改成 `'../data/H20269历史数据.csv'`。**没有采纳**：
那样路径就与「从哪个目录调用」绑死，脆弱且需改约 30 处。
既然 8.2 已 chdir 到项目根，相对路径无需任何改动。

实际改的只有**目录布局本身**变化的部分，由 `tools/fix_paths.py` 完成，
共 12 个文件、31 处替换。该脚本沿用 `build_legacy.py` 的纪律：
**每处替换必须命中预期次数，否则 `exit(1)`** —— 防止「以为改了其实没改」。

### 8.4 验证结果

**核心验收标准：重构不得改变任何计算结果。**

1. **审计回归**：`python tools/audit_checks.py` → **9 PASS / 7 FAIL**，
   与重构前**完全一致**（A/B/C/E/F/G/H/J + LOOKAHEAD 全 PASS；
   7 项 FAIL 均为策略/文档层面的第二批任务，非代码 bug）。
2. **数值交叉核对**：重跑后的报告与 A/B 对比工具的「改后」列逐组比对，
   3 个主力起始日累计收益率差异 **≤ 0.005pp**（纯浮点/四舍五入）。
3. **11 个文件语法校验**通过；10 个模块/脚本从**外部目录**调用无
   import / 路径错误。

### 8.5 执行中发现的额外问题（已修）

1. **`audit_checks.py` 有两处静态检查会因文件搬走而「静默跳过」**
   （`open('data_calculator.py')`、`os.path.exists('run_multiple_backtests.py')`）。
   后者尤其危险：文件找不到时 check_J 会打印「已用 abs() 计算」并判 PASS
   —— **把「没检查」伪装成「没问题」**。
   已加 `src_path()` 解析器（找不到就抛异常）+ 匹配到 0 行即判 FAIL。

2. **发现 3 个「孤儿组」回测**：`2015-05起_深度定投策略`、
   `2015-05起_含交易成本`、`2026-05起_50万本金` —— **没有任何脚本负责生成**，
   是历史上手工跑的，所以每次修 bug 后都会悄悄变旧。其中
   `2015-05起_深度定投策略` 恰好是 `audit_checks.py` 与
   `performance_analysis.py` 的**默认引用组**，当时仍是 2026-07-23 的数据
   （累计 202.81% vs 当前代码 204.45%）。
   已新增 `scripts/run_orphan_backtests.py` 把它们纳入可重复执行范围。

3. **重构差点悄悄毁掉 A/B 工具链**：`build_legacy.py` 从 `core/` 复制源码，
   而注入的 BOOTSTRAP 前言按「上两级目录」推断项目根 —— 副本落在
   `tools/ab_compare/<变体>/` 时会算成 `tools/` 并 chdir 过去，16 组全部
   `nan`。危险在于**已生成的对比报告看起来毫无异样**，但"可完整复现"
   的声明会变成空话。已让 `build_legacy.py` 复制时剥离前言，并验证
   重建结果与存档基线 **656 个数值 0 差异**。

4. **`2015-05起_含交易成本` 与 `2015-05起_深度定投策略` 参数已完全相同**
   （交易成本建模在 0.9 之后成为默认行为），两组必然输出相同数字。
   保留两个目录仅为不破坏历史文档中的引用路径。

---

**文档版本**：v2.0
**创建日期**：2026-08-05
**执行日期**：2026-08-23
**状态**：✅ 方案 C 已执行完毕并通过验证
