# 邮报生成元数据标注实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在每日邮报标题区域之后自动显示实际生成模型和初稿加自动修复的 token 总消耗，并将这项能力安全同步到生产 VPS 与现有 GitHub Draft PR。

**Architecture:** 运行器为每次 Codex 调用捕获私有 JSONL 事件，完整生成流程结束后由独立 Python 模块汇总 `turn.completed`/`response.completed` usage，并将 HTML 注释注入最终正文。用量缺失时只显示“暂不可得”，不猜测；元数据注入失败时阻止 SMTP。公开仓库使用包模块，VPS 使用相同逻辑的根目录脚本副本。

**Tech Stack:** Bash 运行器、Python 3.11+、`unittest`、Codex CLI `--json`/`--output-last-message`、GitHub Draft PR、systemd dry-run 验证。

---

### Task 1: 实现 usage 汇总与 HTML 注释模块

**Files:**
- Create: `src/daily_brief_agent/generation_metadata.py`
- Create: `tests/test_generation_metadata.py`

- [ ] **Step 1: Write the failing unit tests**

在 `tests/test_generation_metadata.py` 中覆盖以下行为：两个 JSONL 文件中的 `turn.completed.usage.total_tokens` 汇总为总量；缺少 `total_tokens` 时使用同一个 usage 对象的 `input_tokens + output_tokens`；无效 JSON 和无关事件不贡献用量；无 usage 时返回不可得；注释插入第一个 `</header>` 之后且保留 `Subject:`；模型中的 `<` 和 `&` 被 HTML 转义；重复注释只保留一条并替换旧值；没有 HTML 插入点时抛出 `ValueError`。

测试应直接调用下列公共接口，先让测试因模块不存在而失败：

```python
from daily_brief_agent.generation_metadata import (
    aggregate_usage,
    annotate_message,
)
```

事件 fixture 使用如下 JSONL 形状，不依赖真实账号或网络：

```json
{"type":"turn.completed","usage":{"input_tokens":10,"output_tokens":5,"total_tokens":15}}
{"type":"item.completed","item":{"type":"agent_message","text":"ignored"}}
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `python -m unittest tests.test_generation_metadata -v`

Expected: FAIL because `daily_brief_agent.generation_metadata` does not yet exist.

- [ ] **Step 3: Implement the smallest tested module**

在 `src/daily_brief_agent/generation_metadata.py` 中实现：

```python
@dataclass(frozen=True)
class UsageSummary:
    total_tokens: int | None
    usage_events: int
    malformed_lines: int


def aggregate_usage(event_files: Iterable[Path]) -> UsageSummary:
    # 逐行读取 JSONL，只接受完成事件中的 usage；
    # total_tokens 优先，缺失时才回退到 input_tokens + output_tokens。
```

实现必须拒绝布尔值、负数和非整数 token 字段；支持 `turn.completed` 与 `response.completed` 两种完成事件及其直接 `usage` 对象；事件文件不存在或不可读时抛出 `OSError`。没有可靠事件时返回 `total_tokens=None`。HTML 注释使用固定 `brief-model-note` class，模型值用 `html.escape(..., quote=True)`，已存在的注释用正则替换；插入点依次为 `</header>`、`</h1>`、`</body>`，均不存在则抛出 `ValueError`。

命令行入口接收：`input`、`output`、`--model` 和可重复的 `--events`，写出 UTF-8 正文并打印不含原始事件内容的诊断行：

```text
generation_metadata=model=<model> total_tokens=<number-or-unavailable> usage_source=<codex_json-or-unavailable>
```

- [ ] **Step 4: Run focused tests to verify they pass**

Run: `python -m unittest tests.test_generation_metadata -v`

Expected: all metadata parsing and HTML annotation tests PASS.

- [ ] **Step 5: Commit the isolated module**

```bash
git add src/daily_brief_agent/generation_metadata.py tests/test_generation_metadata.py
git commit -m "feat: capture daily brief generation metadata"
```

### Task 2: 接入公开 Bash 运行器并覆盖重试总量

**Files:**
- Modify: `scripts/run-daily-brief.sh`
- Modify: `tests/test_runner_retry.py`

- [ ] **Step 1: Extend the runner test fixture before changing the runner**

让 fake Codex 每次调用向 stdout 输出一条 `turn.completed` JSON usage 事件，并让 fake Python 增加 `fake.metadata` 分支，读取 runner 传入的事件文件、将总量插入 fake 邮件标题之后。将 fake 邮件加入 `<h1>`，并在断言中验证初稿 15 tokens 加修复稿 15 tokens 后最终正文只有一条 `brief-model-note`，同时仍验证 SMTP 只调用一次。

- [ ] **Step 2: Run the runner regression test to verify it fails**

Run: `python -m unittest tests.test_runner_retry -v`

Expected: FAIL because the runner does not pass `--json`、事件文件或元数据模块参数。

- [ ] **Step 3: Capture all Codex calls and inject metadata after validation**

在 `scripts/run-daily-brief.sh` 中增加：

```bash
METADATA_MODULE="${BRIEF_METADATA_MODULE:-daily_brief_agent.generation_metadata}"
usage_events="$WORKSPACE/.codex-events-$timestamp.jsonl"
metadata_output="$(mktemp "$WORKSPACE/.metadata-message-$timestamp.XXXXXX.md")"
: > "$usage_events"
trap 'rm -f "$combined_prompt" "$repair_prompt" "$last_output" "$metadata_output" "$usage_events"' EXIT
```

在每次 `run_codex` 的 `codex exec` 参数中加入 `--json`，把 stdout 追加到同一个 `usage_events` 文件，保留 `--output-last-message` 的最终正文行为，并在调用结束后补一行换行以隔离初稿和修复稿事件。校验循环逻辑保持不变；校验成功跳出循环后运行：

```bash
if ! "$PYTHON" -m "$METADATA_MODULE" "$last_output" "$metadata_output" \
  --model "$CODEX_MODEL" --events "$usage_events"; then
  install -m 600 "$last_output" "$LOG_DIR/rejected-message-$timestamp-metadata-failed.md"
  echo "daily_brief_error=generation_metadata_failed" >&2
  exit 1
fi
mv -- "$metadata_output" "$last_output"
```

这样总量自动覆盖首稿及每次修复；事件文件只存在于当前任务私有工作区，并由 trap 删除，不写入公开日志或仓库。

- [ ] **Step 4: Run runner regression and shell syntax checks**

Run: `python -m unittest tests.test_runner_retry -v`

Expected: PASS, including `total_tokens=30` and exactly one metadata note.

Run: `D:/Git/bin/bash.exe -n scripts/run-daily-brief.sh`

Expected: exit code 0 with no shell syntax errors.

- [ ] **Step 5: Commit runner integration**

```bash
git add scripts/run-daily-brief.sh tests/test_runner_retry.py
git commit -m "feat: annotate briefs with total generation usage"
```

### Task 3: 更新公开文档与全量验证

**Files:**
- Modify: `README.md`
- Modify: `docs/model-design.md`

- [ ] **Step 1: Document the observable behavior**

在 README 特性和运行说明中写明：邮报在标题区域之后显示配置模型和本封邮件完整生成流程的 token 总量；总量包括自动修复；用量缺失时显示“暂不可得”；运行时 JSONL 不归档。模型设计文档在输出合同/延迟设计附近补充“元数据由运行器注入，不由模型生成”的边界。

- [ ] **Step 2: Run repository verification**

Run: `python -m unittest discover -s tests -v`

Expected: all tests PASS and no real SMTP connection is made.

Run: `python -m compileall -q src tests`

Expected: exit code 0.

Run: `python tools/privacy_scan.py`

Expected: `privacy_scan=ok findings=0`.

- [ ] **Step 3: Review the diff and commit documentation**

```bash
git diff --check
git status --short
git add README.md docs/model-design.md
git commit -m "docs: describe generation metadata annotation"
```

### Task 4: 同步到 VPS 并做无发送验收

**Files:**
- Create on VPS production root: `generation_metadata.py`
- Modify on VPS production root: `run-daily-brief.sh`
- Create outside the repository: `backups/generation-metadata-YYYYMMDD/`

- [ ] **Step 1: Capture read-back baseline and backup exact production targets**

在 VPS 上只读回读当前 runner、运行时模型、定时器和仓库工作区状态；确认新的备份目录不存在后创建它，并以 `install -m 600` 备份当前 `run-daily-brief.sh`。不修改 systemd timer、收件人、SMTP 或历史邮报。

- [ ] **Step 2: Install the standalone metadata helper and runner changes**

将公开仓库中已测试的 `generation_metadata.py` 复制为生产根目录脚本，调整生产 runner 使用 `METADATA_SCRIPT="$BASE_DIR/generation_metadata.py"` 与 `"$PYTHON" "$METADATA_SCRIPT"`，其余 JSONL 捕获、总量汇总、注释注入和失败阻断逻辑与公开 runner 保持一致。生产 runner 继续使用当前运行时配置中的模型和现有 timer。

- [ ] **Step 3: Run production dry-run checks without SMTP**

执行 Python 编译、metadata fixture、`DAILY_BRIEF_DRY_RUN=1` 的完整运行器验证，并回读输出正文、`generation_metadata=` 日志和 systemd timer。检查 `brief_validation=ok`、`recipient_count=1`、`send_success=1 send_failed=0` 的 dry-run 结果，同时确认没有真实 SMTP 发送；检查正文中 `brief-model-note` 恰好一条并位于标题区域之后。

- [ ] **Step 4: Report the production boundary**

只有上述 dry-run 与配置回读通过才保留 VPS 修改；若 usage 事件未返回，允许 dry-run 显示“暂不可得”，但必须在日志中出现 `usage_source=unavailable`，不能用猜测值替代。真实定时发送留给下一次 11:00/23:00 计划任务验证。

### Task 5: 更新现有 GitHub Draft PR 并检查 CI

**Files:**
- Git branch: `agent/daily-brief-edition-rules`
- Pull request: `reqingonline/daily-brief-agent#1`

- [ ] **Step 1: Confirm the branch contains only intended commits**

```bash
git status --short --branch
git log --oneline --decorate -6
git diff --check origin/main...HEAD
```

Expected: only metadata design, implementation, tests and documentation changes are present; no secrets, logs, VPS paths or Buzzing trial changes are included.

- [ ] **Step 2: Push the branch to update the existing Draft PR**

```bash
git push origin agent/daily-brief-edition-rules
```

Do not merge or change the PR from Draft.

- [ ] **Step 3: Verify GitHub checks and summarize evidence**

```bash
gh pr checks 1
gh pr view 1 --json number,state,isDraft,headRefName,baseRefName,url
```

Expected: PR #1 remains OPEN/DRAFT, head branch is `agent/daily-brief-edition-rules`, base is `main`, and all required CI checks pass. Final report must distinguish local tests, VPS dry-run, and GitHub CI; none alone proves the next real scheduled email was delivered.
