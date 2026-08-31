# Daily Brief Agent

一个面向生产环境的中文全球新闻与市场邮件简报系统。它不是简单的“抓 RSS 后让模型总结”，而是把资料采集、历史去重、联网核验、模型写作、结构化质量校验、错误驱动的完整重写、订阅安全和 SMTP 发送串成一条可审计链路。

## 核心流程

```text
Gmail 订阅预检
    -> 历史简报与“历史上的今天”上下文
    -> 多类别新闻 / 可选 Buzzing 发现 / 事实核查 / 智库 / 战争 / 行情采集
    -> Codex 联网检索与完整 HTML 生成
    -> 本地结构、语言、来源多样性与直链校验
    -> 最多两次错误驱动的完整重写
    -> 按订阅者逐一 SMTP 发送
```

设计原则：**校验失败可以自动修复，但绝不绕过校验发送不合格内容。**

## 特性

- 11 个新闻类别交错采集，避免单一媒体或单一主题占满头部；
- Buzzing 仅作为最多 3 条的可选发现候选池，抓取失败不影响主流程，也不产生独立邮件栏目；
- 独立的事实核查、权威智库、战争观察和市场行情候选池；
- 参考最近简报，减少跨期重复并保持栏目连续性；
- 对全球事件执行来源域名多样性、集中度和直接链接校验；
- 首稿不合格时，将具体错误反馈给模型，最多完整重写两次；
- Gmail 订阅命令只读取邮件头和内联正文，不下载附件、不执行链接；
- 订阅状态原子写入，命令处理有幂等日志，退订后不会被固定收件人重新加入；
- SMTP 按收件人单独发送，日志只输出计数，不暴露地址；
- 每阶段输出稳定的 `key=value` 标记和耗时，方便 systemd/journald 监控；
- 提供 systemd、CI、隐私扫描和隔离的自动修复回归测试。

## 快速开始

要求：Linux、Python 3.11+、Bash、可用的 [Codex CLI](https://github.com/openai/codex) 登录状态，以及 SMTP 账号。Gmail 订阅管理是可选功能。

```bash
git clone https://github.com/reqingonline/daily-brief-agent.git
cd daily-brief-agent
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .

cp .env.example .env
cp config/codex-runtime.env.example config/codex-runtime.env
cp state/subscribers.example.json state/daily-brief-subscribers.json
chmod 600 .env config/codex-runtime.env state/daily-brief-subscribers.json
```

修改示例配置，先执行不发送邮件的测试：

```bash
date +%s > state/subscription-preflight.ok
DAILY_BRIEF_DRY_RUN=1 ./scripts/run-daily-brief.sh
```

Buzzing 候选池默认开启，但它不是必需来源；设置
`DAILY_BRIEF_BUZZING_ENABLED=0` 只会关闭这组补充发现，不会关闭常规新闻、事实核查或质量校验。即使开启，模型也可以在本期完全不选用 Buzzing 内容。

真实部署、Gmail OAuth、systemd 和回滚步骤见 [部署文档](docs/deployment.md)。提示词分层、资料信任边界、质量规则和自动修复机制见 [模型设计](docs/model-design.md)。

## 配置边界

可以提交：

- `config/brief-prompt.txt`：编辑模型和版式规则；
- `config/source-policy.txt`：来源、核验和安全策略；
- 所有 `*.example` 示例文件。

严禁提交：

- `.env`、SMTP 密码、Gmail OAuth 客户端或刷新令牌；
- `state/` 中的真实收件人和命令状态；
- `logs/`、`workspace/`、生成邮件、拒收草稿和资料包；
- VPS 地址、用户名、私钥、生产绝对路径或 Codex 登录状态。

发布前运行：

```bash
python tools/privacy_scan.py
```

## 定时设计

默认 systemd 模板使用 Asia/Shanghai：

- 04:45、16:45：订阅预检；
- 05:00、17:00：开始生成；
- 校验通过后立即发送。

05:00/17:00 是生成卡点，不是保证收件的时刻。实际耗时主要来自联网核验和模型推理，SMTP 通常只占很小一部分。

## 测试

```bash
python -m compileall -q src tests tools
python -m unittest discover -s tests -p 'test_*.py' -v
bash -n scripts/*.sh
python tools/privacy_scan.py
```

测试不会连接真实 SMTP，也不会给任何人发送邮件。

## 许可证

[MIT](LICENSE)


## Star 趋势

<p align="center">
  <a href="https://www.star-history.com/?repos=reqingonline%2Fdaily-brief-agent&amp;type=date&amp;legend=top-left">
    <img src="https://api.star-history.com/chart?repos=reqingonline%2Fdaily-brief-agent&amp;type=date&amp;legend=top-left" alt="reqingonline/daily-brief-agent Star 趋势" width="100%" />
  </a>
</p>
