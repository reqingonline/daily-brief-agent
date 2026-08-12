# 部署指南

本文使用 `/opt/daily-brief-agent` 和专用系统用户 `dailybrief`。如需其他目录或用户，请同时修改四个 systemd 模板，不要只替换部分路径。

## 1. 安装程序

```bash
sudo useradd --system --create-home --home-dir /var/lib/dailybrief --shell /usr/sbin/nologin dailybrief
sudo git clone https://github.com/reqingonline/daily-brief-agent.git /opt/daily-brief-agent
sudo chown -R dailybrief:dailybrief /opt/daily-brief-agent
sudo -u dailybrief python3 -m venv /opt/daily-brief-agent/.venv
sudo -u dailybrief /opt/daily-brief-agent/.venv/bin/python -m pip install --upgrade pip
sudo -u dailybrief /opt/daily-brief-agent/.venv/bin/python -m pip install -e /opt/daily-brief-agent
```

Codex CLI 必须由 `dailybrief` 用户安装并完成认证。认证信息属于该用户的私有运行状态，不应放进仓库或 `.env`。如果 `codex` 不在 systemd 默认 PATH 中，可在 `.env` 中设置 `CODEX_BIN` 为绝对可执行文件路径。

## 2. 创建运行配置

```bash
sudo -u dailybrief cp /opt/daily-brief-agent/.env.example /opt/daily-brief-agent/.env
sudo -u dailybrief cp /opt/daily-brief-agent/config/codex-runtime.env.example /opt/daily-brief-agent/config/codex-runtime.env
sudo -u dailybrief cp /opt/daily-brief-agent/state/subscribers.example.json /opt/daily-brief-agent/state/daily-brief-subscribers.json
sudo chmod 600 /opt/daily-brief-agent/.env /opt/daily-brief-agent/config/codex-runtime.env /opt/daily-brief-agent/state/daily-brief-subscribers.json
```

编辑上述三个文件：

- `.env`：Gmail 所有者、SMTP 服务器、账号和应用密码；
- `config/codex-runtime.env`：Codex 模型与推理强度；
- `state/daily-brief-subscribers.json`：初始订阅者；`owner` 必须与 `GMAIL_OWNER` 一致。

每次修改后运行：

```bash
sudo -u dailybrief /opt/daily-brief-agent/.venv/bin/python - <<'PY'
import json
from pathlib import Path
from daily_brief_agent.subscriber_store import validate_state

path = Path('/opt/daily-brief-agent/state/daily-brief-subscribers.json')
validate_state(json.loads(path.read_text(encoding='utf-8')))
print('subscriber_state=ok')
PY
```

## 3. 可选：启用 Gmail 订阅管理

在 Google Cloud 创建桌面 OAuth 客户端，启用 Gmail API，并将下载的客户端文件保存在：

```text
/opt/daily-brief-agent/secrets/gmail-oauth/client_secret.json
```

设置目录和文件权限：

```bash
sudo -u dailybrief install -d -m 700 /opt/daily-brief-agent/secrets/gmail-oauth
sudo chown dailybrief:dailybrief /opt/daily-brief-agent/secrets/gmail-oauth/client_secret.json
sudo chmod 600 /opt/daily-brief-agent/secrets/gmail-oauth/client_secret.json
sudo -u dailybrief /opt/daily-brief-agent/.venv/bin/python -m daily_brief_agent.gmail_oauth_setup
```

程序只需要 `gmail.modify`，用于读取精确订阅/退订命令、回复结果和添加已处理标签。不要授予不必要的更高权限。

如果不需要邮件订阅管理，可以自行维护订阅状态，并在生成前 30 分钟内将当前 Unix 时间原子写入 `state/subscription-preflight.ok`。

## 4. 先做不发信验收

```bash
sudo -u dailybrief /opt/daily-brief-agent/scripts/run-subscription-preflight.sh
sudo -u dailybrief env DAILY_BRIEF_DRY_RUN=1 /opt/daily-brief-agent/scripts/run-daily-brief.sh
```

验收应至少看到：

```text
subscription_preflight=ok
brief_validation=ok
recipient_count=...
dry_run=1
total_seconds=...
```

Dry run 会生成本地私有草稿，但不会连接 SMTP。

## 5. 安装 systemd

```bash
sudo cp /opt/daily-brief-agent/systemd/*.service /etc/systemd/system/
sudo cp /opt/daily-brief-agent/systemd/*.timer /etc/systemd/system/
sudo systemd-analyze verify /etc/systemd/system/daily-brief-*.service /etc/systemd/system/daily-brief-*.timer
sudo systemctl daemon-reload
sudo systemctl enable --now daily-brief-subscription.timer daily-brief-agent.timer
systemctl list-timers --all daily-brief-subscription.timer daily-brief-agent.timer
```

默认时间（Asia/Shanghai）：

- 10:45、22:45：订阅预检；
- 11:00、23:00：开始生成；
- 通过校验后立即发送。

## 6. 监控

```bash
journalctl -u daily-brief-agent.service -n 100 --no-pager
journalctl -u daily-brief-subscription.service -n 100 --no-pager
```

真实投递的完整成功条件是：

```text
brief_validation=ok
recipient_count=N
send_success=N send_failed=0
```

`timer active` 只证明定时器在等待，不能证明邮件已经生成或送达。查看 `editorial_context_seconds`、`source_collection_seconds`、`model_generation_seconds`、`validation_seconds`、`smtp_seconds` 和 `total_seconds` 可定位耗时阶段。

## 7. 更新和回滚

更新前备份未提交的运行数据：

```bash
sudo install -d -m 700 /var/lib/dailybrief/backup
sudo cp -a /opt/daily-brief-agent/.env /opt/daily-brief-agent/config/codex-runtime.env /opt/daily-brief-agent/state /opt/daily-brief-agent/secrets /var/lib/dailybrief/backup/
```

程序更新使用新目录或 Git 分支验证后再切换。不要用 `git clean` 清理生产目录。回滚时恢复上一提交或上一目录，并恢复四个 systemd 单元后执行：

```bash
sudo systemctl daemon-reload
sudo systemctl restart daily-brief-subscription.timer daily-brief-agent.timer
```

重启 timer 不会立即发送；不要手动启动主 service，除非你明确需要补发并已确认不会重复投递。
