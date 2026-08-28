# 每日邮报事实核查门槛与 Codex 失败可观测性 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复日报因当天没有合适事实核查内容而被错误拦截的问题，并让 Codex 调用的非零退出与空最终输出留下受限诊断证据；保留来源质量、事实依据、收件人和 SMTP 的 fail-closed 边界。

**Architecture:** `validate_brief.py` 将“事实核查”从无条件必需栏目改为条件栏目：缺失时允许通过，出现时继续保留现有结构与全局质量检查。`run-daily-brief.sh` 为每次 Codex 调用分别捕获 stderr、退出状态与 JSON 事件输出；仅在调用失败或空输出时把诊断文件以 600 权限保存在日报日志目录，并将空输出分类为 `codex_output_empty`，不将其伪装成内容校验错误。生产部署只替换已备份的两个目标文件，不改运行环境、收件人、SMTP 参数或 systemd 定时单元。

**Tech Stack:** Python 3.11 标准库、现有 unittest、Bash/systemd timer、SSH/SCP、Asia/Shanghai 时区。

---

## Task 1: 先建立事实核查可省略的回归测试

**Files:** `src/daily_brief_agent/validate_brief.py`, `tests/test_validate_brief.py`

- [x] 在现有 `build_mail()` fixture 增加参数，使测试可以明确构造不含“事实核查”标题但保留其他必需栏目与市场字段的工作日邮件。
- [x] 先写测试：工作日完整邮件缺少“事实核查”时不返回 `required_section_missing:事实核查`；含事实核查标题的既有通过路径继续通过。
- [x] 运行 `python -m unittest tests.test_validate_brief -v`，确认新测试在当前版本先捕获现有阻挡逻辑，再实施最小校验器修改。

## Task 2: 为 Codex 调用增加失败与空输出证据

**Files:** `scripts/run-daily-brief.sh`, `tests/test_runner_retry.py`

- [x] 在 runner 创建受 `umask 077` 保护的 per-run/per-attempt stderr 与 JSON 事件暂存文件；保留现有 `last_output` 清理逻辑。
- [x] 让 `run_codex` 记录真实退出状态；Codex 非零退出时输出 `codex_exit_status=<n>`，并把 stderr/事件文件以 `codex-diagnostics-<timestamp>-<attempt>-<reason>.*` 写入日志目录。
- [x] 将空最终输出记录为 `codex_output_empty`，保留原有最多两次重试与 SMTP fail-closed；空输出重试提示明确要求重新生成完整邮件，不把空输出归因于 validator 内容错误。
- [x] 扩展 runner fake 测试，覆盖 stderr/事件文件受限保存和空输出分类，同时保持现有“校验失败后修复再发送”的回归覆盖。

## Task 3: 本地验证与部署候选准备

**Files:** `src/daily_brief_agent/validate_brief.py`, `scripts/run-daily-brief.sh`, `tests/test_validate_brief.py`, `tests/test_runner_retry.py`

- [x] 使用仓库既有 Python/Bash 环境运行 `python -m unittest discover -s tests -v`、Bash 语法检查、`git diff --check`，不安装全局依赖。
- [x] 使用脱敏样例运行 validator CLI：缺少事实核查的 23:00/工作日邮件应通过，存在其他质量错误仍应失败。
- [x] 只准备上述两个生产平铺文件的部署候选，核对内容与现有生产入口的路径/导入关系；不复制真实配置、认证、收件人或邮件内容到公开文件。

## Task 4: Lightsail 备份、原子部署与远端回归

**Files on VPS:** `$APP_ROOT/run-daily-brief.sh`, `$APP_ROOT/validate_brief.py`

- [x] 写入前核对目标文件 hash/mtime/owner、最近失败日志与 timer 状态；确认只操作 Lightsail 日报目录，不接触 EC2、代理核心或 SMTP 参数。
- [x] 在既有 `backups` 下创建带 Asia/Shanghai 时间戳的逐文件备份，保存目标文件原 hash 与权限；通过受限临时目录上传候选，先做 `bash -n`、`py_compile` 和昨晚拒绝稿 validator 重放。
- [x] 仅在远端回归通过后原子替换两个目标文件；重新读回 hash、权限、systemd timer 状态，并确认运行环境、状态文件和收件人文件未变。
- [ ] 不手动补发昨晚邮件、不手动触发生产任务；等待下一次原定任务，真实验收仍要求新日志同时出现 `brief_validation=ok`、`recipient_count=1`、`send_success=1`、`send_failed=0`。在该计划任务完成前，不能声称邮件发送已恢复。

## Task 5: 交付记录

- [x] 回读本地 diff 与远端文件 hash，记录备份路径、远端回归输出摘要和未验证边界；不写入 token、密钥、完整 bearer URL、私有邮件正文或收件人数据。
- [x] 提交本次源码、测试、变更记录和实施计划，推送到当前 GitHub `feature/commodity-futures-earnings` 分支；不自动合并或修改其他分支。
- [x] 更新本计划复选框和当前任务报告，明确区分“认证已恢复”“代码/配置修复已部署”“GitHub 分支已同步”和“下一次真实邮件尚待验收”。
