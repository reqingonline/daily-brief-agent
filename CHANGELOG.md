# 变更记录

本文件按提交记录本仓库每次提交实际更新的内容和日报板块。提交代码、配置、测试或文档时，必须在同一个提交中补充一条记录；如果一次提交同时影响多个板块，逐项列出。不要把生产收件人、VPS 地址、绝对生产路径、运行日志、邮件正文或凭据写入这里。

记录格式：

```text
## YYYY-MM-DD · commit message
- 提交：<短 hash；提交前可写 commit message，提交后补齐 hash 时另建一条记录>
- 栏目/模块：<日报板块或内部模块>
- 更新：<具体改动>
- 验证：<测试、校验或未验证边界>
```

## 2026-08-28 · fix: make fact-check section conditional and retain Codex diagnostics

- 提交：`<commit after push>`
- 栏目/模块：事实核查质量闸门、日报 runner、Codex 生成失败诊断
- 更新：事实核查在当天没有合适候选时允许省略，但不放宽其他栏目、来源多样性、财报官方链接或 SMTP 发送闸门；Codex 非零退出与空最终输出分别记录退出状态、stderr 和 JSON 事件诊断，并继续 fail-closed，不向收件人发送未通过校验的邮件。
- 验证：新增事实核查可省略、空输出重试与非零退出诊断回归测试；完整测试和 Bash 语法检查通过。生产下一次原定任务的真实发送结果仍需单独验收，未手动补发昨晚邮件。

## 2026-08-22 · fix: allow weekend briefs without market sections

- 提交：`fix: allow weekend briefs without market sections`（提交前记录）
- 栏目/模块：周末版质量闸门、市场总览、国际期货与大宗商品、股票与指数、下一次财报
- 更新：移除 Bash 中重复且无上下文的 generated_quality_gate 业务检查，改为轻量输出预检并统一交给 validator；按 Asia/Shanghai 周六、周日省略并禁止市场/期货/股票/财报板块，跳过周末财报链接校验；补齐 23:00 版历史板块规则，并把财报链接校验限定在“股票与指数”板块，避免普通新闻“官方公告”链接被误判为财报。
- 验证：新增周末允许省略、拒绝市场板块、跳过财报链接和 23:00 版规则的回归测试；生产真实邮件发送将在下一次自动定时运行观察，不手动补发。

## 2026-08-21 · docs: design commodity and earnings sections

- 提交：`c57fcab`
- 栏目/模块：国际期货与大宗商品、股票与指数、下一次财报、02513.HK 身份核验
- 更新：记录六个期货合约、财报日期与当日官方链接闸门、周末省略规则，以及公开仓库与 Lightsail 生产边界。
- 验证：设计文档完成自检；生产地址、收件人和运行时秘密未进入公开文件。

## 2026-08-21 · docs: add commodity and earnings implementation plan

- 提交：`29b7624`
- 栏目/模块：采集器、财报日历、日报 prompt、来源策略、validator、Lightsail 部署、GitHub Draft PR
- 更新：将实现拆为 registry、结构化日期、官方链接、质量闸门、本地回归、备份回滚、真实邮件验收和公开仓库发布任务。
- 验证：通过 `git diff --check`、占位符扫描和公开性扫描。

## 2026-08-21 · feat: add commodity and earnings support

- 提交：随本功能实现提交
- 栏目/模块：国际期货与大宗商品、股票与指数、下一次财报、02513.HK、采集健康、日报验证
- 更新：新增六个 Yahoo 期货 registry、期货分组与单位字段、下一次财报结构化记录、Nasdaq 日期适配、SEC 当日一手公告闸门、过期链接拒绝规则；更新 source bundle、prompt、来源策略和工作日 validator；`02513.HK` registry 保留 HKEX 官方更名公告链接。
- 验证：提交前运行完整 Python 测试、编译检查、Bash 语法检查和隐私扫描；真实供应商可用性与 Lightsail 结果在部署记录中单独复核。
