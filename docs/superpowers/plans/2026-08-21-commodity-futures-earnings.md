# 国际期货与财报栏目 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在每日邮报中增加国际粮食、金银铜期货/大宗商品候选，以及股票观察名单的下一次财报发布日期；只有在“今日正式发布且可核验”的情况下才附上官方财报链接。同步核实并将 `02513.HK` 标记为香港上市的智谱公司 `Z.AI`/中文简称“智谱”，在公开仓库和 Lightsail 生产副本分别完成可验证更新。

**Architecture:** 将期货行情作为市场数据采集器中的独立 registry 与渲染分区，不混入股票行情；将财报逻辑放入独立的 `earnings_calendar` 模块，采用“结构化下一次日期 + 当日官方披露链接”的数据模型和 fail-closed 链接闸门。公开仓库只保存代码、配置模板和脱敏 fixture；生产环境继续使用私有维护索引所指向的 Lightsail 平铺脚本，通过逐文件备份和原子替换回填同等逻辑。邮件层只消费候选数据，由 prompt 决定最终叙事，validator 负责检查结构、时效和链接边界。

**Tech Stack:** Python 3.11 标准库、现有 `source_collector.py`/`validate_brief.py`、RSS/JSON/HTML 数据源、pytest/unittest 现有测试、Bash systemd timer、GitHub Draft PR、SSH/SCP；时区统一 `Asia/Shanghai`。

---

## Task 1: 建立可审计的期货与股票 registry

**Files:** `src/daily_brief_agent/source_collector.py`, `tests/test_source_collector.py`

- [ ] 在市场定义附近新增 `FUTURES_SYMBOLS`，固定覆盖六个独立候选：国际粮食（小麦、玉米、大豆/豆粕或现有供应商可稳定取得的代表合约）、黄金、白银、铜；每条记录包含内部 key、显示名称、供应商代码、单位/合约说明和数据源优先级。保留现有股票/指数 registry，不把 futures key 混进股票筛选。
- [ ] 将生产观察名单的 26 个股票/公司记录抽成可复用的 `STOCK_WATCHLIST`，并在 `02513.HK` 记录中写入 `Z.AI（智谱）`、代码、市场和“名称已由 HKEX 公告核实”的来源注释；不把未经核验的中文全称或宣传性描述写进 prompt。
- [ ] 为 CNBC/Yahoo/Tencent 当前解析链增加期货代码映射与归一化字段：`symbol`、`name`、`price`、`change`、`change_pct`、`unit`、`source`、`as_of`、`status`。单个期货失败只产生可识别的 unavailable 候选，不让全局市场健康闸门误报成功。
- [ ] 为 parser 增加脱敏 fixture 测试，覆盖正常报价、缺字段、百分比格式、期货单位、单个源失败和 02513 display-name 映射；断言原有股票/指数输出不变，且不把 secrets、完整请求 URL 或认证头写入日志/fixture。
- [ ] 运行 `python -m unittest discover -s tests -v`（必要时先按仓库约定设置 `PYTHONPATH=src`），确认新增测试与当前 `main` 基线共同通过；失败时只修本任务涉及的兼容性。

## Task 2: 实现下一次财报与当日官方链接模型

**Files:** `src/daily_brief_agent/earnings_calendar.py`, `src/daily_brief_agent/source_collector.py`, `tests/test_earnings_calendar.py`

- [ ] 新建独立的财报模块，定义不可变记录或等价数据结构，至少包含 `symbol`、`display_name`、`next_date`、`date_precision`、`announcement_date`、`official_url`、`source`、`status`、`retrieved_at`；日期统一解析为 `Asia/Shanghai` 的 `date`，未知/盘前盘后信息不伪造具体时刻。
- [ ] 实现 provider 适配层：先消费可稳定返回的结构化财报日历字段，再按股票市场选择官方披露入口；provider、HTTP 状态、解析失败原因均进入内部诊断字段，邮件正文只保留可用事实。代码必须允许 fixture 注入，不能让单次网络失败阻塞整封日报。
- [ ] 实现严格的官方链接闸门：`next_date` 永远只保留下一次发布日期；`official_url` 只有当公告发布日期按 `Asia/Shanghai` 等于当天、域名属于已配置的一手披露域名且 HTTP/内容校验通过时才输出，否则强制为空。已过期公告不再显示链接；当日仍在抓取中的公告不能推断为已发布。
- [ ] 为 `AAPL NVDA SNDK AMD WDC GOOG AMZN QCOM SKHX CAT BA KO AAL C BXMT JPM AXP CF NTR IBM ORCL NET BABA 02513.HK 688825.SH 001232.SZ` 建立代码到显示名/市场/官方披露域名的脱敏配置；对于无法取得下一次日期的公司输出 `status=unavailable`，不得把旧财报日期当成下一次日期。
- [ ] 写 fixture 测试覆盖：未来日期、今天发布且官方链接通过、昨天发布链接被清空、非官方域名被拒、无日期、跨时区边界、单公司 provider 超时；断言输出永远不会包含过期链接或搜索结果页链接。
- [ ] 运行 `python -m unittest tests.test_earnings_calendar -v` 与完整现有测试，保存失败用例的真实错误而不是用默认日期兜底。

## Task 3: 把候选数据接入日报 prompt、渲染和质量闸门

**Files:** `config/brief-prompt.txt`, `config/source-policy.txt`, `src/daily_brief_agent/source_collector.py`, `src/daily_brief_agent/validate_brief.py`, `tests/test_validate_brief.py`, `tests/test_source_collector.py`

- [ ] 在 source bundle 中新增独立标题 `国际期货与大宗商品候选` 和 `下一次财报候选`，每个候选保留来源、采集时间、状态和可用于编辑的结构化事实；市场数据失败时明确标注 unavailable，不用上一交易日数据冒充实时数据。
- [ ] 更新 prompt：工作日市场总览中加入粮食、黄金、白银、铜的价格/涨跌与单位；股票段按“下一次财报日期”优先展示即将发生事项；只有候选中的 `official_url` 非空且 `announcement_date` 是当天时，才在对应财报后附链接；不得为已过日期补旧链接或自行猜测财报日。
- [ ] 更新 source policy：商品价格使用一手/高可信市场数据；财报日期优先公司 IR、交易所或监管披露，聚合器仅作日期发现/交叉核验；正式链接必须回到公司 IR、HKEX、SEC、交易所或其他配置的一手域名；明确 `02513.HK = Z.AI（智谱）` 的 HKEX 核验事实。
- [ ] 扩展 validator 的结构检查：工作日要求两个新 h2 分区存在且有状态字段；检查财报链接只允许配置的一手域名、链接发布日期等于当天、链接对应公司和代码，拒绝 Google News、搜索结果页、旧公告链接和 `url` 占位符；周末继续遵守现有市场/历史栏目规则，不强制生成虚假的当日数据。
- [ ] 增加测试：工作日完整期货与财报段通过、周末不误报、当日官方链接通过、过期链接被拒、非官方链接被拒、缺失单家公司不阻塞、02513 显示名和代码同时出现；运行全量测试、`git diff --check`，并用脱敏样例运行 validator CLI。

## Task 4: 本地回归、隐私扫描和可发布提交

**Files:** changed files only; `docs/superpowers/specs/2026-08-21-commodity-futures-earnings-design.md`; `docs/superpowers/plans/2026-08-21-commodity-futures-earnings.md`

- [ ] 检查 Python 版本和仓库本地虚拟环境；使用仓库已有环境执行完整测试、编译检查和 validator/source collector dry-run，不安装全局依赖，不把真实 API key、邮箱、IP、SSH key、bearer URL、Gmail 内容或生产路径写入公开文件。
- [ ] 用 `rg` 扫描变更内容中的私有主机地址、私有文件系统路径、凭据文件名、PEM 私钥块、bearer/auth 头、邮箱地址和完整敏感 URL；检查 fixture、日志和异常文本没有泄露请求头/凭据。
- [ ] 检查 `git status --short`、`git diff --stat`、`git diff --check`、分支名和最近提交；仅 stage 本功能涉及的精确路径，创建一个实现提交和一个必要的文档提交，保留现有 Draft PR #1 的分支与内容不变。
- [ ] 推送 `feature/commodity-futures-earnings` 到 `reqingonline/daily-brief-agent`，用 `main` 为 base 创建 Draft PR，正文列出测试结果、数据源/官方链接闸门、未验证边界和“公开仓库提交不等于生产部署”；不自动合并。

## Task 5: 将同等逻辑安全回填到 Lightsail VPS

**Files on the private Lightsail app root:** `source_collector.py`, `validate_brief.py`, `config/brief-prompt.txt`, `config/source-policy.txt`, plus any explicitly required flat-file module/config. Resolve the real root and SSH target from the private maintenance index immediately before writing; do not copy those private values into this public plan or repository.

- [ ] 写入前重新只读检查 Lightsail 的 hostname、目标文件 hash/mtime、systemd timer 状态、当前运行版本和最近一封日报日志；确认目标是私有维护索引标记的 Lightsail 日报主机，不触碰 EC2。若 hash 或文件结构与本计划假设不同，先按现状调整补丁，不覆盖用户改动。
- [ ] 在 VPS 的既有备份目录建立带 Asia/Shanghai 时间戳的逐文件备份，记录原 hash、权限、owner/group 和目标清单；使用 SCP 上传到受限临时目录，再通过原子替换/逐文件 `install` 更新，保留现有 env、state、recipient 和 systemd 单元不变。
- [ ] 将公开实现适配为生产平铺入口：不直接把 `src/daily_brief_agent/...` 当作 root-level script 覆盖；明确导入路径、相对路径和现有 `run-daily-brief.sh` 调用关系，新增模块缺失时先上传同目录文件并运行 `py_compile`/import 检查。
- [ ] 先执行远程 collector dry-run、validator fixture/样例检查和 shell `bash -n`；确认输出出现两个新候选标题、`02513.HK` 的 `Z.AI（智谱）` 显示名、下一次财报日期字段，且不存在敏感值。失败时立即从本次备份恢复并重新检查 hash。
- [ ] 只在 dry-run 通过后让现有 timer 继续按原计划运行，不手工发送测试邮件；随后读取一次有新运行结果的 journal，必须看到 `brief_validation=ok`、`recipient_count=1`、`send_success=1`、`send_failed=0`，并读取新 Gmail 日报确认期货和财报版面真实出现。服务 active 本身不作为完成证据。

## Task 6: 生产结果复核与交付记录

**Files:** `docs/superpowers/plans/2026-08-21-commodity-futures-earnings.md` and local verification notes only if needed

- [ ] 对最终公开仓库记录：分支、实现提交、Draft PR URL、CI/测试结果；对生产环境单独记录：目标文件 hash、备份目录、dry-run 输出摘要、timer/journal 证据和 Gmail 实际邮件主题/时间。不得把邮件正文中不必要的个人信息复制进仓库。
- [ ] 将未能证实的项目单独列为 unresolved：供应商当天是否提供某合约、个别公司下一次财报日为空、盘前/盘后时区差异、官方公告尚未发布等；不以推断填补。
- [ ] 最终回读 `git diff`、生产文件 hash 和新日报，确认没有误改 EC2、没有修改收件人/凭据/定时计划、没有把旧链接遗留到正文；完成后更新计划复选框并以证据分开说明“代码已发布”和“VPS 真实日报已验证”。
