# AstrBot Keyword Reply Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` or `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 当前交付仅为计划；只有用户要求开始开发后才执行。子代理方式由用户选择，不因本文自动启动代理。

**Goal:** 为 QQ / OneBot v11 / AstrBot 4.28 实现可在原生面板配置的文字关键词回复插件，覆盖句式捕获、直接回复、随机候选、权限管理和稳定运行。

**Architecture:** `main.py` 只负责 AstrBot 事件、命令和生命周期，纯 Python 引擎负责规则校验、匹配、渲染和策略。面板文件保存规则，插件数据目录保存运行时禁用和轮询状态；通过不可变配置快照和发送资格预留控制并发。

**Tech Stack:** Python 3.12；AstrBot `>=4.28,<4.29`；标准库；`regex>=2024.11.6,<2027`；测试使用 pytest、pytest-asyncio，代码检查使用 Ruff。执行时记录实际解析到的依赖版本，不在本次规划阶段安装环境。

**Spec:** [设计说明](../specs/2026-09-29-astrbot-keyword-reply-design.md)。实施者必须先读设计说明，配置字段和边界以该说明为准。

## Global Constraints

- 运行环境：QQ、OneBot v11、AstrBot 4.28，主要用于群聊。
- Python 3.12 开发基线；插件声明 AstrBot `>=4.28,<4.29`，只承诺验证过的 4.28 系列。
- 首版仅文字，支持多条候选、随机选择、变量替换。
- 普通群消息可以触发；每条规则可以要求必须直接 @机器人。
- 仅 AstrBot 配置中的机器人管理员；QQ群主、群管理员身份不自动获得权限。
- 默认按优先级只回复一条；可切换随机一条、命中多条。
- 成功回复后不追加 AstrBot 默认 AI 回复，其他插件仍可处理。
- 群冷却 3 秒；同用户同规则冷却 10 秒；可以设为 0。
- 整句匹配、捕获不能为空；相同优先级按配置顺序。
- 多条回复默认最多 3 条；这是本插件的上限，不包含其他插件发送的消息。
- 面板配置是规则的唯一来源；聊天开关只保存负向限制。
- 测试指令不修改冷却、去重、随机数状态、轮询位置或正式统计。
- 不依赖模型服务、不执行用户表达式、不将捕获文字解释为 CQ 码。
- 不修改 AstrBot 核心，不宣称未实际测试的平台实现已兼容。

---

## 实施顺序与交付物

依赖链：任务 1 → 任务 2 → 任务 3 → 任务 4 → 任务 5 → 任务 6 → 任务 7 → 任务 8 → 任务 9 → 任务 10。

前 6 项可在不启动 AstrBot 的环境中测试；任务 7 开始进入真实框架集成；任务 10 要求真实 QQ 测试群。每项在测试通过后独立提交。当前目录没有 Git 仓库：实际开始开发时若仍如此，再执行 `git init`，规划阶段不初始化仓库、不提交文档。

### 预期文件结构

```text
astrbot_plugin_keyword_reply/
├── main.py                         # Star、事件/命令注册、生命周期
├── metadata.yaml                   # 插件名称、版本、平台与框架范围
├── _conf_schema.json               # 中文原生配置表单
├── requirements.txt                # 插件运行依赖 regex
├── pyproject.toml                  # 开发依赖、pytest 与 Ruff 配置
├── README.md                       # 安装、使用、限制与故障排查
├── CHANGELOG.md
├── keyword_reply/
│   ├── __init__.py
│   ├── models.py                   # 数据类型、结果与错误码
│   ├── config.py                   # 默认值、类型校验、范围校验
│   ├── matching.py                 # 普通词与句式模板
│   ├── regex_matching.py           # 正则编译、预算与超时
│   ├── rendering.py                # 文字变量编译和单次替换
│   ├── scope.py                    # 群/用户/平台/At 条件
│   ├── engine.py                   # 只读评估、编译快照
│   ├── policy.py                   # 冷却、概率、选择、预留、提交
│   ├── storage.py                  # 原子状态存储和分区
│   ├── service.py                  # 发送工作流、有限并发
│   ├── commands.py                 # 命令参数解析与诊断文本
│   └── astrbot_adapter.py          # 提取正文和构造 MessageContext
├── examples/
│   └── rules.json                  # 与表单真实字段一致的示例
├── tests/
│   ├── conftest.py
│   ├── test_config.py
│   ├── test_matching.py
│   ├── test_regex.py
│   ├── test_rendering.py
│   ├── test_engine.py
│   ├── test_policy.py
│   ├── test_storage.py
│   ├── test_service.py
│   ├── test_commands.py
│   ├── test_schema.py
│   └── integration/
│       ├── test_astrbot_adapter.py
│       └── test_astrbot_pipeline.py
└── docs/
    ├── superpowers/                # 本计划与设计说明
    └── acceptance.md               # 真实 OneBot 验收记录
```

实现根目录就是当前工作目录，不需要再套一层相同名字的插件目录。纯引擎包可直接用 pytest 导入；插件在 main.py 中使用相对导入，兼容 AstrBot 动态加载。不要通过 sys.path 修改掩盖打包问题。

## 公共接口约定

下面是跨任务的接口合同。数据类型均在 `models.py` 定义，之后的任务不得自行换名或新增同义模型。

| 类型 | 必须具备的字段 |
| --- | --- |
| `ScopeKey` | frozen dataclass：`platform_id: str, bot_id: str, chat_type: str, target_id: str` |
| `MessageContext` | frozen dataclass：`scope: ScopeKey, user_id: str, user_name: str, message_id: str, text: str, mentioned_bot: bool` |
| `Rule` | frozen dataclass；设计说明 4.2 的字段各自成为同名属性，另加 `order: int`；集合使用 tuple/frozenset |
| `PluginConfig` | frozen dataclass；设计说明 4.1 的字段各自成为同名属性 |
| `ConfigIssue` | `rule_id: str | None, path: str, code: str, message: str` |
| `LoadedConfig` | `settings: PluginConfig, rules: tuple[Rule, ...], issues: tuple[ConfigIssue, ...]` |
| `ConfigError` | ValueError 子类；`issues: tuple[ConfigIssue, ...]`；仅整体不可应用时抛出 |
| `Match` | `keyword: str, text: str, groups: dict[str, str]`；组字典包含数字组号和命名组，均为字符串键 |
| `Trace` | `rule_id: str, reason: str, detail: str`；detail 不含用户完整原文 |
| `Candidate` | `rule: Rule, match: Match, replies: tuple[str, ...]` |
| `Evaluation` | `candidates: tuple[Candidate, ...], traces: tuple[Trace, ...], exhausted: bool` |
| `CompiledRule` | `rule: Rule, matcher: CompiledMatcher, replies: ReplyTemplates` |
| `Snapshot` | `revision: str, settings: PluginConfig, rules: tuple[CompiledRule, ...], issues: tuple[ConfigIssue, ...]` |
| `Delivery` | `rule_id: str, text: str, next_cursor: int | None` |
| `Reservation` | `token: str, scope: ScopeKey, user_id: str, message_id: str, deliveries: tuple[Delivery, ...], revision: str` |
| `SendOutcome` | `rule_id: str, attempted: bool, success: bool, error_code: str | None` |
| `HandleResult` | `reason: str, sent_rule_ids: tuple[str, ...]` |

`Rule` 的字符串枚举与默认值见设计说明；ID 列表为 `tuple[str, ...]`，时长和概率为 float，开关为 bool，优先级/顺序/长度为 int，候选与词表为 `tuple[str, ...]`。`CompiledMatcher` 和 `ReplyTemplates` 分别由 matching.py、rendering.py 定义，models.py 用 TYPE_CHECKING 防止循环导入。

统一跳过原因：`disabled`、`wrong_platform`、`wrong_chat_type`、`scope_denied`、`needs_at`、`excluded`、`no_match`、`invalid_rule`、`empty_reply`、`reply_too_long`、`duplicate`、`group_cooldown`、`rule_cooldown`、`user_cooldown`、`probability`、`busy`、`regex_timeout`、`budget_exhausted`、`send_failed`。成功结果为 `sent`。

时间通过注入的 `clock: Callable[[], float]` 获取单调时钟；随机通过独立的 `random.Random` 注入；发送通过 `send: Callable[[str], Awaitable[None]]` 注入。测试不得依赖真实等待、真实 QQ 网络或全局 random。

## Task 1：配置模型、校验和最小开发环境

**Files:** Create `keyword_reply/models.py`, `keyword_reply/config.py`, `keyword_reply/__init__.py`, `pyproject.toml`, `requirements.txt`, `tests/conftest.py`, `tests/test_config.py`。

**Interfaces:** `load_config(raw: dict) -> LoadedConfig`；全局错误抛 `ConfigError`，单条规则错误写入 issues 且不进入 rules。为后续任务提供上述数据类型。

- [x] 创建 Python 3.12 虚拟环境，在 pyproject.toml 定义 pytest、pytest-asyncio、Ruff 开发依赖，并在 requirements.txt 写入 `regex>=2024.11.6,<2027`。不把 AstrBot 当插件运行依赖重复安装，真实框架在集成阶段单独提供。
- [x] 创建基础 fixture 和以下失败测试。`raw_rule` 仅提供必填值，其余字段由 load_config 生成设计说明中的默认值。

```python
@pytest.fixture
def raw_rule():
    return {
        "id": "echo",
        "name": "句式回复",
        "match_type": "template",
        "pattern": "我{关键词}什么",
        "capture_mode": "any",
        "replies": ["是啊{关键词}什么"],
    }


def test_defaults(raw_rule):
    loaded = load_config({"rules": [raw_rule]})
    assert loaded.settings.group_cooldown_seconds == 3.0
    assert loaded.rules[0].user_rule_cooldown_seconds == 10.0
    assert loaded.rules[0].match_scope == "full"


def test_duplicate_id_rejects_entire_snapshot(raw_rule):
    with pytest.raises(ConfigError):
        load_config({"rules": [raw_rule, dict(raw_rule)]})


def test_bad_rule_is_isolated(raw_rule):
    bad = dict(raw_rule, id="bad", probability=2)
    result = load_config({"rules": [raw_rule, bad]})
    assert [r.id for r in result.rules] == ["echo"]
    assert result.issues[0].path == "rules[1].probability"
```

- [x] 运行 `python -m pytest tests/test_config.py -q`，确认未实现入口导致失败；不要把环境缺失当作需求测试失败。
- [x] 按设计说明 4.1/4.2 逐字段解析。禁止 `bool("false")`、静默把 float 转 ID、接受 NaN 概率；未知业务字段记录错误，允许表单元字段 `__template_key`。
- [x] 按以下顺序实现，保证错误路径可定位：

```text
验证顶层对象 → 补全全局默认值 → 验证类型/数值边界
→ 检查规则总数和全部 ID 唯一性 → 分别解析每条规则
→ 对单条错误生成 ConfigIssue → 冻结成功模型
```

- [x] 增加空词表、空回复、布尔值冒充整数、超过规则数、非法 ID、私聊枚举和禁用但配置无效的用例，重新运行该测试文件。
- [x] 通过后提交 `feat: define keyword reply configuration and validation`。

## Task 2：六种匹配模式与有界正则

**Files:** Create `keyword_reply/matching.py`, `keyword_reply/regex_matching.py`, `tests/test_matching.py`, `tests/test_regex.py`。

**Interfaces:** `compile_matcher(rule: Rule) -> CompiledMatcher`；matcher 暴露 `capture_names: frozenset[str]` 和 `search(raw_text: str, *, timeout_s: float) -> Match | None`。超时抛内置 `TimeoutError`，编译失败转 `ConfigIssue` 由 Task 4 汇总。

- [x] 为下列输入矩阵建立参数化测试，模板通过 Task 1 fixture 和 load_config 创建。

```python
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("我吃什么", "吃"),
        ("我学习什么", "学习"),
        ("我什么", None),
        ("我   什么", None),
        ("今天我吃什么", None),
        ("我吃什么？", None),
    ],
)
def test_template_full_match(raw_rule, text, expected):
    rule = load_config({"rules": [raw_rule]}).rules[0]
    found = compile_matcher(rule).search(text, timeout_s=0.01)
    assert (found.keyword if found else None) == expected
```

- [x] 运行 `python -m pytest tests/test_matching.py tests/test_regex.py -q`，确认具体行为尚未实现而失败。
- [x] 普通匹配按「最靠左 → 最长 → 配置顺序」选择关键词；精确模式匹配整个正文，前/后缀分别固定一端。
- [x] 实现模板 token 解析、字面转义和一个槽位约束。内部组名固定为 `kw`，显示槽位仍为中文。示意编译规则如下，不允许直接把用户句式当正则：

```python
slot = rf"(?P<kw>[^\r\n]{{{rule.capture_min},{rule.capture_max}}}?)"
# prefix/suffix 来自已校验 token，使用 regex.escape；词表模式把 slot
# 换成按长度降序 escape 后的候选分支，并且验证捕获长度。
pattern = regex.escape(prefix) + slot + regex.escape(suffix)
# full 调用 fullmatch；search 调用 search；捕获从原始字符位置取值。
```

- [x] 归一化保留位置映射：只裁首尾空白、可选裁末尾问号、可选 ASCII A-Z 转 a-z，不改字符长度。返回的 keyword/text 使用原始正文对应切片；模板不跨行。高级正则直接针对保留原文字形的裁剪文本使用匹配标志；开启 ignore_case 时使用 ASCII 大小写模式并在 README 说明其字符类语义。
- [x] 正则用 `regex.compile`，匹配调用 `pattern.search(text, timeout=remaining_seconds)` 或 fullmatch。限制 pattern 长度；超时不吞成普通 no_match，保留 `regex_timeout` 诊断原因。
- [x] 增加词表限定、`吃`/`吃饭`重叠、search 模式、Emoji、转义花括号、特殊标点、正则命名与编号捕获、可选组为空、病态正则超时测试。避免以单次硬件耗时断言替代超时行为断言。
- [x] 全部通过后提交 `feat: add literal template and timeout regex matching`。

## Task 3：回复模板与候选渲染

**Files:** Create `keyword_reply/rendering.py`, `tests/test_rendering.py`。

**Interfaces:** `compile_replies(rule: Rule, capture_names: frozenset[str]) -> ReplyTemplates`；`render_all(templates: ReplyTemplates, match: Match, message: MessageContext, *, max_chars: int) -> tuple[str, ...]`。编译返回文字/token 列表，运行替换只有一遍。

- [x] 在 conftest.py 增加 `message` fixture：平台 p1、机器人 9000、群 1000、用户 2000/小明、消息 m1、正文我吃什么、未 At。
- [x] 写出变量替换、注入保持字面和未知变量失败测试。例如：

```python
def test_capture_is_not_evaluated_again(raw_rule, message):
    rule = load_config({"rules": [raw_rule]}).rules[0]
    templates = compile_replies(rule, frozenset())
    match = Match(keyword="{用户ID}", text="我{用户ID}什么", groups={})
    assert render_all(templates, match, message, max_chars=2000) == ("是啊{用户ID}什么",)
```

- [x] 运行 `python -m pytest tests/test_rendering.py -q` 确认失败，再实现单遍 tokenizer。只识别设计说明变量表；`{{`、`}}`输出字面括号；禁止 Python format 的索引、属性和格式说明语法。
- [x] 实现上下文值映射和 fallback：用户名为空时取 user_id，私聊群 ID 为空。正则编号/名称必须在 capture_names 中，未参与的合法组值为空。
- [x] 对每个候选渲染一次，过滤空白文本和超过 max_reply_chars 的文本；全部无效时该规则没有可发送候选，诊断记录原因。不要截断捕获内容或把 CQ 文本转成消息组件。
- [x] 增加中文、换行、重复变量、未知变量、花括号、缺失用户名、可选组、渲染膨胀超长测试。通过后提交 `feat: render safe text reply templates`。

## Task 4：范围过滤、规则编译和只读评估

**Files:** Create `keyword_reply/scope.py`, `keyword_reply/engine.py`, `tests/test_engine.py`。

**Interfaces:** `compile_snapshot(raw: dict, revision: str) -> Snapshot`；`scope_reason(rule: Rule, message: MessageContext) -> str | None`；`evaluate(snapshot: Snapshot, message: MessageContext, *, clock: Callable[[], float]) -> Evaluation`。evaluate 不访问网络、磁盘、RNG 或可变运行状态。

- [x] 写白/黑名单冲突、require_at、私聊开关、同优先级顺序和编译错误隔离测试：

```python
def test_blacklist_wins(raw_rule, message):
    raw_rule.update(allowed_user_ids=["2000"], blocked_user_ids=["2000"])
    snapshot = compile_snapshot({"rules": [raw_rule]}, "r1")
    evaluation = evaluate(snapshot, message, clock=lambda: 0.0)
    assert evaluation.candidates == ()
    assert evaluation.traces[0].reason == "scope_denied"
```

- [x] 运行 `python -m pytest tests/test_engine.py -q` 确认失败。
- [x] 编译快照依次调用 load_config、compile_matcher、compile_replies，汇总每条规则错误，保持原 order。按 `(-priority, order)`排序成功规则。
- [x] 在 evaluate 中先检查配置总开关、私聊总开关、全局平台/用户限制，再按设计说明流程产生 Candidate 和 Trace；全局原因的 Trace.rule_id 使用 `*`。匹配超时隔离当条规则，总预算耗尽返回 `Evaluation((), traces, exhausted=True)`，不能发送预算耗尽前搜到的部分结果。
- [x] 用注入 clock 控制总预算测试；每次 matcher timeout 为「单规则上限与总剩余时间」的较小值。配置编译只在加载时发生，不随每条消息重复。
- [x] 添加搜索捕获、多个词返回稳定关键词、排除词先于匹配、输出超长候选过滤、全局错误不生成快照测试。通过后提交 `feat: compile rule snapshots and evaluate scoped messages`。

## Task 5：回复策略、冷却、去重与原子发送资格

**Files:** Create `keyword_reply/policy.py`, `tests/test_policy.py`。

**Interfaces:** `RuntimePolicy(clock, rng)`；`async reserve(snapshot, message, evaluation) -> Reservation | None`；`async complete(reservation, outcomes: tuple[SendOutcome, ...]) -> None`；`preview(snapshot, message, evaluation) -> tuple[Trace, ...]`；`export_persistent() -> dict`；`restore_persistent(data: dict) -> None`。跳过原因由 policy.last_reason(message) 查询，状态键按 ScopeKey。

- [x] 构造可手动推进的 FakeClock 以及固定种子的独立 RNG；不要通过 sleep 测冷却。
- [x] 写出以下测试以及 all 模式的一次事件多个 Delivery 测试：

```python
@pytest.mark.asyncio
async def test_only_one_concurrent_group_reservation(snapshot, message, evaluation):
    policy = RuntimePolicy(clock=lambda: 100.0, rng=random.Random(7))
    a, b = await asyncio.gather(
        policy.reserve(snapshot, message, evaluation),
        policy.reserve(snapshot, replace(message, message_id="m2"), evaluation),
    )
    assert sum(item is not None for item in (a, b)) == 1
```

`snapshot` 和 `evaluation` fixtures 在此任务添加，分别由默认 raw_rule 编译、evaluate 得到。

- [x] 运行 `python -m pytest tests/test_policy.py -q` 确认失败。
- [x] reserve 在同一短临界区内完成检查和占位；临界区不执行匹配、不 await 网络/磁盘。顺序必须固定：

```text
运行时禁用/暂停 → 去重/在途事件 → 群 busy/冷却
→ 候选规则冷却 → 每规则一次概率抽样
→ priority/random/all 选择 → first/random/round_robin 选候选
→ 生成唯一 token，写入在途状态 → 返回 Reservation
```

- [x] complete 根据实际成功列表提交群/规则/用户冷却与游标；失败不推进；至少尝试发送就保留事件去重，全部未尝试则释放。使用 token 防止过期 complete 释放其他事件的预留。finally 清理 busy。
- [x] 加入 p=0/1、概率失败后的低优先级接替、冷却后的接替、random 模式候选集合、同级顺序、reply round_robin、多条上限、部分发送失败和缺失消息 ID 测试。
- [x] preview 只读状态并返回诊断，不调用 rng；前后对 `rng.getstate()`、export_persistent()、冷却/统计快照做相等断言。
- [x] 实现 TTL 和容量回收；容量耗尽时不增长无界字典。管理禁用项不按普通缓存淘汰。
- [x] 通过后提交 `feat: enforce reply selection cooldowns and deduplication`。

## Task 6：持久化与服务工作流

**Files:** Create `keyword_reply/storage.py`, `keyword_reply/service.py`, `tests/test_storage.py`, `tests/test_service.py`。

**Interfaces:** `StateStore(path: Path)`：`async load() -> dict`, `async save(data: dict) -> None`；`ReplyService(snapshot, policy, store, clock)`：`async handle(message: MessageContext, send) -> HandleResult`, `async apply_config(raw: dict, revision: str) -> tuple[ConfigIssue, ...]`, `async update_runtime(action: str, rule_id: str | None, scope: ScopeKey, global_scope: bool) -> None`, `async diagnose(message: MessageContext, rule_id: str | None) -> str`, `async close() -> None`。

- [x] 存储测试覆盖中文状态往返、非法 JSON、版本不是 1、临时写失败、replace 失败、文件不存在。损坏状态备份保留，插件以「自动回复暂停」恢复并报告，不能静默开启原本暂停的规则。
- [x] 服务测试覆盖成功、失败、部分成功和引擎 busy。发送用注入函数，例如：

```python
@pytest.mark.asyncio
async def test_send_failure_does_not_advance_cursor(service, message):
    before = service.policy.export_persistent()

    async def broken_send(text):
        raise OSError("OneBot unavailable")

    result = await service.handle(message, broken_send)
    assert result.sent_rule_ids == ()
    assert result.reason == "send_failed"
    assert service.policy.export_persistent() == before
```

- [x] 运行 `python -m pytest tests/test_storage.py tests/test_service.py -q` 确认失败。
- [x] 实现 StateStore：异步接口通过 `asyncio.to_thread` 执行文件 I/O；同目录写 temp，flush/fsync 后 os.replace，异常保留旧文件，所有操作串行。
- [x] 数据路径设为 `data/plugin_data/astrbot_plugin_keyword_reply/<profile_hash>/state.json`，profile_hash 为规范化绝对配置路径的 SHA-256 前 16 位；状态带 `version: 1`。原子写保存失败时不提交管理状态快照。
- [x] 用有两个 token 的 `asyncio.Queue` 做匹配工作许可池，`get_nowait()` 无许可立即返回 busy。拿到许可后 `await asyncio.to_thread(evaluate, ...)`，finally 归还，不用不可终止线程超时制造后台积压。
- [x] 服务获得候选后调用 reserve，再依次 await send 并收集 SendOutcome；以 finally 调用 complete。发送不得持有全局配置锁，配置更新只替换快照，已经进入处理的事件继续使用旧快照。
- [x] apply_config 在工作线程编译成功后原子替换；全局编译错误保留旧对象；成功更新不重置仍存在规则的 cooldown/dedup，删除规则时剔除孤立游标和禁用 ID。在途事件 complete 只提交当前仍存在规则的持久状态，不能复活已删除 ID。
- [x] 管理状态修改立即持久化；游标合并每 30 秒保存；两者经过同一个串行写入口和递增 revision，禁止旧刷盘快照覆盖新管理状态。增加交错保存测试。候选列表改变时游标按新长度取模；close 停止后台循环、等待有界匹配工作结束、刷盘，重复 close 安全。
- [x] 通过后提交 `feat: persist runtime controls and coordinate reply delivery`。

## Task 7：AstrBot / OneBot 消息接入与 AI 共存

**Files:** Create `main.py`, `metadata.yaml`, `keyword_reply/astrbot_adapter.py`, `tests/integration/test_astrbot_adapter.py`, `tests/integration/test_astrbot_pipeline.py`。

**Interfaces:** `extract_message(event) -> MessageContext`；Star 的 `__init__(context, config)`、`initialize()`、自动消息 handler、`terminate()`。main.py 调用 ReplyService，不重新实现引擎规则。

- [x] 在独立集成环境使用官方 AstrBot v4.28.0 以及用户实际 4.28.x 补丁版本；记录版本和测试命令。未取得用户的实例时使用本地框架测试，并在最终验收记录中明确真实群未验收。
- [x] 先写消息提取测试：顶层 Plain 拼接、引用正文排除、真实 At 判定、群号取 get_group_id、自己的 QQ 号过滤、平台实例隔离、前缀保持。

```python
def test_raw_plain_is_used_when_framework_stripped_prefix(onebot_event):
    onebot_event.message_str = "我吃什么"
    onebot_event.message_obj.message = [Plain("/我吃什么")]
    extracted = extract_message(onebot_event)
    assert extracted.text == "/我吃什么"
```

`onebot_event` fixture 用真实 4.28 AstrBotMessage 和平台元数据构造，send 替换为可控适配器；不能靠一个随意 mock 的私有字段证明框架兼容。

- [x] 运行 `python -m pytest tests/integration/test_astrbot_adapter.py -q` 确认行为失败，再实现提取与平台判断。正文不从已经剥离唤醒词的 event.message_str 获取。
- [x] 注册自动消息入口，示意公共 API 用法如下：

```python
@filter.platform_adapter_type(filter.PlatformAdapterType.AIOCQHTTP)
@filter.event_message_type(filter.EventMessageType.ALL, priority=10)
async def on_message(self, event: AstrMessageEvent):
    message = extract_message(event)
    await self.service.handle(message, lambda text: event.send(event.plain_result(text)))
```

正式入口在调用 service 前还须排除管理事件、自身消息和 command 前缀；示意不能替代这些检查。正常自动回复不要调用 stop_event，不直接写 `_has_send_oper`，不自行调用 LLM。

- [x] 写真实 ProcessStage 集成断言：成功发送后默认 Agent 不被调用；未命中且原本唤醒时 Agent 可被调用；其他 handler 继续；冷却、发送失败、regex_timeout 不强行关闭原流程。检查 4.28.0 对 `should_call_llm` 的消费逻辑，但实现不依赖该方法。
- [x] initialize 加载状态与配置，启动每 2 秒检查 config.config_path 修改时间的任务；保存触发后解析并 apply_config。检查任务和游标刷盘任务都在 terminate 中取消并清理。完整框架重载后的新对象负责重新加载，不遗留旧任务。
- [x] metadata 填 name/display_name/version/desc/support_platforms（aiocqhttp）/astrbot_version。作者与仓库地址使用实施时真实项目资料，禁止编造发布仓库；本地验收无需发布到市场。
- [x] 通过后提交 `feat: integrate keyword replies with AstrBot 4.28 OneBot events`。

## Task 8：管理员命令和可解释测试

**Files:** Create `keyword_reply/commands.py`, `tests/test_commands.py`；Modify `main.py`。

**Interfaces:** `parse_command(text: str) -> ParsedCommand | None`；`ParsedCommand(action: str, rule_id: str | None, scope: str, text: str, page: int)` 在 commands.py 定义；`async execute_command(service, command, context, is_admin: bool) -> str` 返回只包含文字的报告。

- [x] 先按设计说明的完整命令表写参数化测试，包括权限拒绝、未知 ID、非法页码、here/global、中文别名、testat、暂停后仍能 resume。

```python
def test_test_command_keeps_body_whitespace():
    parsed = parse_command("kwr test echo 我  吃什么\n第二行")
    assert parsed.action == "test"
    assert parsed.rule_id == "echo"
    assert parsed.text == "我  吃什么\n第二行"
```

- [x] 运行 `python -m pytest tests/test_commands.py -q` 确认失败。解析管理语法用有限次 split，仅提取指令名、动作、ID，其余正文原样保留；不执行 shell，不使用 shlex 改写测试正文。
- [x] 命令 handler 优先级设为 100，明确机器人管理员鉴权；所有管理路径同一鉴权入口，包括 list/show/test。识别到管理命令即标记 `keyword_reply.management_event`；自动监听同时检查标记和指令名，未授权管理命令也不能当自动回复正文处理。
- [x] on/off/pause/resume/reset 只通过 update_runtime 修改运行状态，here/global 互不混淆。on/resume 不解除面板禁用、黑名单或其他层级的暂停，报告具体剩余限制。
- [x] test/testat await service.diagnose，使用与正式消息同一个 evaluate/render 路径和有限匹配工作许可，仅取 policy.preview；testat 把模拟 MessageContext.mentioned_bot 设为 true。报告顺序为「总体结论 → 规则命中 → 捕获 → 候选 → 冷却/概率/排序 → 错误」。概率显示数值，不抽样；随机不实际选择候选。暂时没有匹配许可时直接报告忙，不增加正式 busy 统计。
- [x] 写测试前后服务状态深比较，验证 RNG、游标、去重、冷却、统计和文件没有变化。仅真正执行的管理开关保存状态，查看和测试不得写文件。
- [x] list 每页 10 项；报告输出上限 4000 字符，超过时显示省略条数和下一页方式。说明显示的候选是诊断文本，不是向群里逐条实际发送候选。
- [x] 通过后提交 `feat: add admin controls and side-effect-free rule diagnostics`。

## Task 9：中文配置表单、示例和使用文档

**Files:** Create `_conf_schema.json`, `examples/rules.json`, `README.md`, `CHANGELOG.md`, `tests/test_schema.py`。

**Interfaces:** Schema 输出必须被 load_config 正确解析；默认规则列表可以为空，示例从 examples/rules.json 复制。列表模板统一复用同一字段名，不为 UI 增加第二套业务字段。

- [x] 先写 Schema 与业务默认值对应、模板字段无遗漏、全部示例编译成功的测试：

```python
def test_all_examples_are_valid():
    raw = json.loads(Path("examples/rules.json").read_text(encoding="utf-8"))
    snapshot = compile_snapshot(raw, "examples")
    assert snapshot.issues == ()
    assert len(snapshot.rules) == len(raw["rules"])
```

- [ ] 运行 `python -m pytest tests/test_schema.py -q` 确认失败，再创建「关键词」「句式」「正则」三个原生模板；字段保存结构保持扁平，通过描述前缀与排序组织基本/匹配/范围/回复/限制，中文说明必须写明空列表、0 秒、概率0/1、full/search 的语义。
- [x] 使用原生支持的 string/text/bool/int/float/object/list/template_list；候选回复为 string 列表，一项一条，不用换行拆分多条候选，因为单条文字本身允许换行。
- [x] 填写下列完整可运行示例，全部默认 `enabled=false`，由用户按需启用：

```json
{
  "rules": [
    {"id":"template_words","name":"限定吃喝","enabled":false,
     "match_type":"template","pattern":"我{关键词}什么",
     "capture_mode":"keywords","keywords":["吃","喝"],
     "replies":["是啊{关键词}什么"]},
    {"id":"template_any","name":"自由接话","enabled":false,
     "match_type":"template","pattern":"我{关键词}什么",
     "capture_mode":"any","replies":["是啊{关键词}什么"]},
    {"id":"goodnight","name":"晚安","enabled":false,
     "match_type":"contains","keywords":["晚安"],
     "reply_mode":"random","replies":["晚安，{用户名}！","早点休息～"]},
    {"id":"regex_echo","name":"正则接话","enabled":false,
     "match_type":"regex","pattern":"^我(?P<动作>.+?)什么$",
     "replies":["是啊{捕获.动作}什么"]}
  ]
}
```

- [x] README 按用户任务编写：安装到 data/plugins、配置第一条规则、切换词表/任意模式、设置群限制、随机回复、管理员开关、测试不命中的原因、保存生效、升级备份、纯文字限制与 AI 共存。明确 `[关键词]` 是示意，实际用 `{关键词}`。
- [ ] 在真实 4.28 WebUI 手动新增每种模板，保存后重新打开，核对类型与 list 结构；验证只输入关键字段即可工作，高级选项无需全填。不能只依赖 Schema JSON 语法检查声称 UI 可用。
- [ ] 通过后提交 `docs: add native configuration forms and keyword reply examples`。

## Task 10：整体回归、性能和真实 QQ 验收

**Files:** Create `docs/acceptance.md`；按测试结果只修改有证据的问题所在文件。

**Interfaces:** 本项不新增功能，输出可复查的测试记录和可安装插件目录/压缩包。

- [x] 执行完整自动化检查：

```powershell
python -m pytest tests -q
python -m ruff check .
python -m ruff format --check .
python -m compileall -q main.py keyword_reply
```

单元测试可独立运行；integration 需要真实 AstrBot 环境。如果分两个环境运行，分别记录成功/失败数量，禁止把跳过集成测试描述为集成通过。

- [x] 在本地记录 500 条普通规则、4096 字符消息、至少 1000 次评估的中位数/p95，预热后计时；目标普通规则 p95<50ms，网络发送时间不计入。另测混合正则、超时规则和高并发许可池；不做未经测量的吞吐承诺。
- [ ] 在测试群按以下顺序验收，每步记录消息、配置摘要、实际结果、日期和实际 OneBot 实现：

| 步骤 | 操作 | 预期 |
| --- | --- | --- |
| 1 | 启用词表规则，发我吃什么、我学习什么 | 只前者回复 |
| 2 | 切换任意捕获，发我学习什么 | 是啊学习什么 |
| 3 | 发晚安，配置两个候选 | 每次只有一个候选，长期可选到两个 |
| 4 | 同一消息配置高/低优先级规则 | priority 模式只高优先级；同级按顺序 |
| 5 | 高优先级进入单规则冷却 | 低优先级可接替，前提是群冷却也已解除 |
| 6 | 切换 random/all，配置超过3条命中 | random一条；all最多3条 |
| 7 | 开启 require_at，普通发送、直接At、引用、AtAll | 只有直接At满足该条件 |
| 8 | 在两个群和两个用户发送，切换独立会话设置 | 群冷却按真实群隔离；用户规则冷却正确 |
| 9 | 模拟同消息ID重复和不同ID同正文 | 重投不回复；真实重复遵守冷却后可回复 |
| 10 | 普通成员、仅QQ群管理员、AstrBot管理员执行命令 | 只有最后一种获得管理权限 |
| 11 | 执行 test/testat，再发真实消息 | 测试不消耗冷却、不推进轮询 |
| 12 | 面板保存、非法正则、非法全局配置、重载 | 有效修改生效；局部隔离/全局保留旧配置；无重复回复 |
| 13 | 配置 here/global 禁用并重启 | 状态正确持久化；on不越过面板禁用 |
| 14 | 唤醒消息命中/不命中，同时保留另一个测试插件 | 命中无默认AI追加；未命中照常；其他插件继续 |
| 15 | OneBot发送失败后恢复 | 不重试刷屏、不推进失败游标、插件仍可继续处理 |
| 16 | 卸载/重载、检查后台任务 | 原任务清理，无重复监听或持续写盘 |

- [ ] 根据证据修复失败，重跑对应测试及受影响集成测试，再做一次最终检查。通过后才填写验收结果；真实 QQ 环境不可用时明确列为未验收，不伪造通过。
- [x] 整理安装包，排除 .venv、.git、缓存、测试群消息与实际运行状态。用户只要求本地插件时不发布市场、不创建远程仓库。
- [ ] 提交 `test: verify keyword reply behavior on AstrBot 4.28`，报告版本、测试结论、真实群验收范围和已知限制。

## 覆盖关系与完成定义

| 需求 | 对应任务 |
| --- | --- |
| 词表与任意捕获、直接回复、六种模式 | 1、2、4 |
| 文字候选、变量、安全替换 | 3、5 |
| 群/用户/平台/At 范围 | 4、7 |
| 优先级、随机、多条、概率 | 5 |
| 冷却、并发、去重、错误恢复 | 5、6 |
| 管理员权限、开关、测试 | 7、8 |
| 面板编辑、热应用、数据不互相覆盖 | 1、6、7、9 |
| 默认 AI 共存、其他插件继续 | 7、10 |
| 安装、说明、真实 QQ 验收 | 9、10 |

实施完成意味着：设计说明中的首版行为均有实现，相关自动化检查通过，真实环境验收结果如实记录，用户得到可安装插件与中文用法。编写本计划不代表这些实现或测试已经完成。
