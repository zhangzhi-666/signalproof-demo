# SignalProof API 与命令行约定

本接口适用于项目支持的信号表达式语言。Web Worker、CLI 与 Python 调用共用 `engine` 核心，不依赖外部模型服务。

## 1. Python 入口

```python
from engine import verify, dispatch
from engine.service import InputError

steps = ["LT(D(x(t),t),t,s)", "s*X(s)-2"]
context = {"initial": {"x0": 2}}

result = verify(steps, context)
# 等价调用：verify(steps, c=context)
# JSON 调度接口中的字段名则是 context。
result = dispatch({"action": "verify", "steps": steps, "context": context})
```

函数签名：`verify(steps, c=None) -> dict`、`dispatch(data) -> dict`。`verify` 没有 `context=` 关键字参数。非法输入抛出 `InputError`，不转换为“数学未知”。直接 Python 调用不包含子进程超时；需要墙钟限制时使用 CLI 或自行隔离进程。

常用调度动作：

| `action` | 请求 | 返回 |
| --- | --- | --- |
| `verify`（省略时默认） | `steps`，可选 `context` | 整链结论、逐步证据与显示信息 |
| `format` | `steps` | 每行 LaTeX、ROC LaTeX、排版错误 |
| `catalog` | 无其他必需字段 | 规则目录、规则数、内置样例、引擎与格式版本 |

## 2. 验证请求

```json
{
  "action": "verify",
  "steps": [
    "ZT((1/2)^n*u(n),n,z)",
    "z/(z-1/2); ROC: abs(z)>1/2"
  ],
  "context": {}
}
```

`steps` 是 2–16 个字符串组成的数组，数组顺序就是推导行顺序。不在未验证的相邻表达式之间预设等号。`context` 可省略或为 `null`，按空条件处理。

| 条件字段 | 类型 / 示例 | 含义 |
| --- | --- | --- |
| `causal` | 布尔值，如 `true` | 声明信号因果；不能与非零的 `0-` 初值同时声明 |
| `initial` | `{"x0": 2, "x1": -1}` | 初值 `x(0-)` 与一阶导数初值；也支持 `h0/h1/g0/g1/y0/y1` |
| `positive` | `["a"]` | 支持的变量名具有正值前提 |
| `nonzero` | `["a", "b"]` | 支持的变量名非零；允许保留消去因子所需的定义域条件 |
| `definitions` | `{"X(w)": "1/(1+I*w)"}` | 声明已知频域函数；最多 8 项 |

初值必须是有限数值且绝对值不超过 `1e8`。参数列表只接受支持的变量名，不接受任意条件字符串。变换对键支持 `X/H/G/Y` 与 `w/s/z` 的组合，如 `X(s)`、`H(z)`；右侧需是具体表达式，不能继续引用未定义信号或变换。未给出的初值或 ROC 不自动补造。

## 3. 表达式语法

| 写法 | 作用 |
| --- | --- |
| `FT(x(t),t,w)` | Fourier，变量固定为 `t,w` |
| `LT(x(t),t,s)` | 从 `0-` 开始的单边 Laplace，变量固定为 `t,s` |
| `ZT(x(n),n,z)` | 双边 Z，变量固定为 `n,z` |
| `Conv(x(t),h(t),t)` | 卷积 |
| `D(x(t),t)` / `D(x(t),t,2)` | 一阶 / 二阶导数 |
| `Int0(x(t),t)` | 从 0 到当前自变量的积分 |
| `delta(t)` / `u(t)` | 冲激 / 阶跃 |
| `exp`、`sin`、`cos`、`sqrt`、`abs`、`conjugate`、`re`、`log` | 白名单单参数函数 |

信号函数包括 `x/h/g/y` 及频域函数 `X/H/G/Y`。乘法必须写 `*`；幂支持 `^` 或 `**`，虚数单位为 `I` 或 `j`，圆周率为 `pi`。支持将 `ω/τ/π/−/×` 转换为对应计算符号。`n/k/m` 为整数变量；`t/w/a/b/c/q/v/tau/T/w0` 及初值符号为实数；`s/z` 默认可取复数。

ROC 写在表达式之后，每行最多一个条件：

```text
1/(s+2); ROC: re(s)>-2
z/(z-1/2); ROC: abs(z)>1/2
```

ROC 支持当前解析器识别的单个半平面或圆内外条件，不支持任意逻辑组合、复杂环域或隐式集合。能解析某个条件不代表已经证明该条件；ROC 的方向、开闭边界和变换变量仍需核验。

输入只接受数学 AST 白名单；拒绝属性访问、导入、下标、推导式和任意函数。表达式主体最多 1200 字符、250 个 AST 节点、22 层嵌套，数值常量绝对值上限 `1e8`、数值指数绝对值上限 16。输入限制用于约束规模，不保证任何符号问题都在固定时间内完成。

## 4. 验证结果

`status` 的四种数学状态：

| 值 | 含义 |
| --- | --- |
| `correct` | 所有相邻步骤有符号等价或规则依据 |
| `wrong` | 至少存在一个已确认错误，附规则冲突或合法反例等证据 |
| `unknown` | 尚无已确认错误，但存在条件不足或无法证明 / 否定的步骤 |
| `incomplete` | 尚无错误或未知步骤，但必要 ROC 信息缺失 |

整链状态优先级为 `wrong → unknown → incomplete → correct`。`wrong` 不意味着其前面的未知步骤已被证实。

主要顶层字段：

| 字段 | 说明 |
| --- | --- |
| `summary` | 适合显示的中文结论 |
| `firstError` | 第一个已确认错误的**目标行号**，从 1 开始；无确认错误时为 `null` |
| `firstErrorCertain` | 存在首错时，是否已排除前缀中的未知 / 不完整步骤；为 `false` 时只能称“最早已确认错误” |
| `steps` | 相邻步骤结果；N 行输入产生 N−1 项 |
| `correction` | 输入链的副本，只尝试替换首个已确认错误行；不保证修改后的整链正确 |
| `normalized` / `ast` | 标准表达式与文本树，用于查看；不能独立作为正确性证据 |
| `latex` / `rocLatex` | 与输入行一一对应的公式及 ROC 排版字符串 |
| `elapsedMs` / `formatVersion` | 核心返回的耗时元数据 / 排版版本；正式性能统计以基准程序外层计时为准 |

每个 `steps` 元素包含：

- `before`、`after`、`line`：原始相邻公式与目标行号。
- `localStatus`、`status`、`statusLabel`：该相邻变形自身的判断和显示标签。
- `inherited`：此前已有确认错误；后续局部正确不代表整条推导恢复正确。
- `ruleIds`、`ruleNames`、`conditions`、`evidence`、`explanation`：规则、前提及判断依据。
- `trace`：规则重写路径；`samples`：可复核反例；`diff`：候选与提交式的局部结构差异，可能为空。
- `expected`：可用的候选修正式，可能为空；不是任意情况下都能生成答案。
- `beforeLatex`、`afterLatex`、`expectedLatex` 及相应 `beforeRocLatex`、`afterRocLatex`、`expectedRocLatex`：分开渲染表达式和条件。

LaTeX 仅负责展示，排版失败不能改变数学判定。不要把 `firstError=null` 单独当作“正确”，还必须检查 `status`。

## 5. 格式化接口

```python
preview = dispatch({
    "action": "format",
    "steps": ["z/(z-1/2); ROC: abs(z)>1/2"]
})
for row in preview["lines"]:
    print(row["latex"], row["rocLatex"], row["error"])
```

格式化每次最多 16 行，可按行返回错误而保留其他行的预览。返回结构为 `{"formatVersion": "…", "lines": [...]}`；每行有 `latex`、`rocLatex`、`error`。`error` 非空时应显示原始输入或错误说明。预览成功只表示语法可排版，不表示推导正确。

## 6. CLI 合约

以下命令在仓库根目录执行，Windows 无需激活环境：

```powershell
python tools/setup.py
.\.venv\Scripts\python.exe -m engine verify examples/z-complete.json --pretty --require-correct
.\.venv\Scripts\python.exe -m engine verify examples/fourier-shift.json --timeout 15 --output build/diagnosis.json
.\.venv\Scripts\python.exe -m engine format examples/z-complete.json --pretty
.\.venv\Scripts\python.exe -m engine catalog --pretty
.\.venv\Scripts\python.exe -m engine serve --port 8080
```

`verify` 和 `format` 接受 UTF-8 JSON 文件，支持 BOM；文件位置也可写 `-`，从标准输入读取。单个 JSON 请求最多 100000 字节。命令名决定执行动作，覆盖请求里的 `action`。`--pretty` 格式化输出，`--output` 保存 UTF-8 JSON；不传则写到标准输出。

`verify/format/catalog` 在可终止的子进程中执行，`--timeout` 默认 15 秒，范围为大于 0 且不超过 300 秒，包含该子进程启动耗时。`serve` 只监听本机 `127.0.0.1`，不受此请求超时控制。

| 退出码 | 含义 |
| --- | --- |
| `0` | 请求完成；普通 `verify` 仍需检查 JSON 中的数学状态 |
| `1` | 使用 `--require-correct`，但整链结果不是 `correct` |
| `2` | 输入、执行或格式化行错误；格式化失败仍可返回有效行的预览 |
| `3` | 子进程超时，输出 `status: unknown`、`timedOut: true` 及说明 |

CLI 请求错误输出 `{"status":"error","error":"…"}`。命令行参数用法错误由 `argparse` 输出到标准错误。CLI 的 `error`/`timedOut` 是执行层结果，不能与引擎的数学 `unknown` 混为一项准确率标签。

## 7. 测试与测量契约

[固定数据](../data/tests.json)包含 100 条推导和 110 次相邻变形；[独立逐步标签](../data/step-oracles.json)通过数据哈希绑定，不由实际运行结果生成。[追加回归](../data/holdout.json)单独统计 32 条推导、41 次相邻变形。

`tools/benchmark.py` 使用持续存活的隔离工作进程，每次请求有墙钟超时；报告同时保存核心调用时延与含 IPC 的调用者时延。超时保留失败行，核心时延为 `null`，不从准确率分母删除。`uniqueMetrics` 使用每个 ID 首次结果，`metrics` 汇总全部重复；不能把重复次数当作独立样本数。

步骤准确率比较 `localStatus` 与逐步标签；错误链首错准确率同时要求实际 `status=wrong` 且目标行号匹配。原始测量见 [JSON](benchmark-results.json) / [CSV](benchmark-results.csv)，设计与指标解释见[实验报告](experiment-report.html)。
