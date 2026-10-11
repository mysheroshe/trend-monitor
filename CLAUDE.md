 # trend-monitor

## 项目说明
AI/Tech 趋势监控工具，自动采集热点数据，生成日报和周报，通过邮件发送。

## 技术栈
- Python
- GitHub Actions（自动化）
- Gmail SMTP（发邮件）

## 项目结构
- main.py：日报入口
- weekly_report.py：周报入口
- collectors/：数据采集模块（6个数据源）
- reporters/：报告生成
- senders/：邮件发送
- storage/：数据持久化
- analyzers/：数据分析模块（周报分析 + indie机会分析）
- data/daily/：每日采集的原始数据JSON
- reports/weekly/：生成的周报
- analysis/daily/：每日 indie 机会分析报告（{date}-indie.md）

## 数据源（按优先级）
1. Product Hunt
2. Toolify.ai（最新工具 + Trending榜单）
3. There's An AI For That
4. Chrome Extensions
5. GitHub Trending
6. Hacker News

## 注意事项
- 环境变量放在 .env，不要提交到 git
- GitHub Actions 定时触发：日报每天 7:00 AM PST，周报每周日 22:00 PST
- 邮件发送用 Gmail App Password，不是账号密码
- 之前踩过坑：Chrome Extensions 用动态搜索而非硬编码ID
- Toolify.ai 有 Cloudflare 保护，必须用 Playwright（requests 会被 403）；需在 Actions 中执行 `playwright install chromium --with-deps`
- Toolify fetch_toolify_tools() 返回 dict {'new': [...], 'trending': [...]}，存储时合并为平铺列表
- collectors/__init__.py 需要显式导出 fetch_toolify_tools，否则 `from collectors import *` 不包含它
- HTML 报告生成到 docs/index.html，由 GitHub Pages 提供访问；daily workflow 每次运行后自动 commit+push
- workflow commit 用 [skip ci] 防止无限循环触发
- collectors 函数名：fetch_product_hunt_posts, fetch_trending_repos, fetch_hackernews_posts（不是 fetch_product_hunt/fetch_github_trending/fetch_hackernews）

## Indie 分析模块（2026-03-18 新增）

### 核心逻辑（analyzers/indie_analyzer.py）— Phase 1 已重写
- 主流程：`normalize_products`（归一化+同日去重）→ `filter_unsuitable_products`（硬过滤）
  → `score_product`（加权 0–100）→ `rank_products`（按 ranking_score 排序）
- 公开函数：`normalize_products`, `normalize_name`, `normalize_url`,
  `filter_unsuitable_products`, `filter_reason`, 7 个维度函数
  (`score_build_ease`, `score_self_service_acquisition`, `score_monetization`,
  `score_low_communication`, `score_operating_cost`, `score_solo_builder_fit`,
  `score_tool_orchard`), `source_confidence`, `source_adjustment`,
  `score_product`, `rank_products`, `generate_indie_report`, `deep_analyze_product`
- 权重/常量集中在 `config/scoring_weights.py`（Build Ease 20、Self-Service 15、
  Monetization 15、Low Communication 15、Operating Cost 10、Solo-Builder Fit 15、
  Tool-Orchard 10 = 100）
- **极性**：`build_ease` 5 = 很容易（旧的 `tech_difficulty` 已删除，禁止再引入反向指标）
- 来源置信度只做 ±5 分的排序微调，永不救活劣质产品
- 关键词匹配统一走 `_has()`：纯字母数字的短词按词边界匹配（避免 `ai` 命中 `email`、
  `reel` 命中 `freelancers`）
- 过滤逻辑：企业/演示门槛、CRM/销售运营、代运营/咨询、双边市场、硬件、加密、
  基础设施、受监管、专有数据、GitHub 库；普通词（analytics/platform/AI）不过滤
- HN 过滤：`Show HN` / `Launch HN` 视为产品，新闻/观点帖不进入排名
- 领域检测：14个领域表，读 name+description（不用tags），驱动8个问题的个性化回答
- 8问框架：用户是谁 / 为什么需要 / 如何找用户 / 商业模式 / 关键洞察 / 一句话Pitch / 能否独立开发 / 如何获客 + 💡第一步行动
- 注意：`generate_indie_report` 的 toolify_data 参数接受 dict({'new':[], 'trending':[]}) 或 list，内部自动处理
- 注意：所有分析均为规则/关键词驱动，无 LLM API 调用
- 注意：时间一律走 `config/timeutil.py`，不要再用 `datetime.now()` 或裸 `ZoneInfo`

### HTML 报告（analyzers/indie_html_generator.py）
- 函数签名：`generate_indie_html(indie_report_markdown, product_data)`
- product_data 结构：`{product_hunt, toolify, ai_tools, chrome_extensions, github, hackernews}`
- 内部调用 `rank_products`（与 markdown 同一套流程，避免两边结果不一致）
- 表格新增列：Confidence / Score /100 / 7 个维度 / Why this score
- URL 解析：GitHub → 构造 `https://github.com/{name}`；其他用 link/url/website 字段
- 输出：`docs/indie.html`，由 GitHub Pages 提供访问

### 数据持久化（storage/data_store.py + .gitignore + daily-report.yml）— Phase 1 已修复
- `.gitignore` 必须保留 `!/data/daily/*.json` 例外，否则每日 JSON 不会被提交
- workflow 用 `git add -A -- data/daily analysis/daily`，不要再加 `|| true`

### 测试（tests/）
- `pip install -r requirements-dev.txt && pytest`（当前 62 个用例）

## 机会聚类 + 关键词（Phase 2 新增）

### analyzers/clustering.py
- 聚类主流程：`classify`（单产品归类）→ `assign_clusters`（分组+去重）→
  `build_cluster`（聚合）→ `score_cluster`（簇评分）→ `rank_clusters`；
  入口 `analyze_clusters(products, data_dir=None, today=None)`
- 聚类键规则（保守）：`domain:function`（如 tattoo:generation）→
  仅“创作型领域”（DEFAULT_GENERATION_DOMAINS）→ `domain:generation` →
  具体领域单独成簇 `domain:general` → 其余单个产品各自成簇（键含名称哈希，
  绝不用产品名当 ID）
- `GENERIC_DOMAIN_ONLY_DOMAINS = {text, data, code, website}` 不允许单独成簇
  （太宽泛，容易过度合并）
- `cluster_id` = 簇键的 slug（如 `tattoo-generation`），跨天/跨输入顺序稳定
- 簇评分：`cluster_score` = 最佳成员分 + 成员数加成(≤9) + 来源多样性加成(≤12)
  + 来源置信度(±5) + 持续性(≤7) − 仅 HN(−20) − 单产品(−12)；
  低于 QUALITY_FLOOR(60) 时加成减半；`cluster_score_breakdown` 可测试
- 历史信号：`load_history_clusters` 只读 data/daily（28 天上限），
  当天不重复计入；无历史时 days_seen=1 并写 `history_note`，不编造数据

### analyzers/keyword_candidates.py
- `generate_keyword_candidates(cluster)` → 5–15 条候选，字段
  keyword / priority(HIGH|MEDIUM|LOW) / type(CORE_TOOL|LONG_TAIL_TOOL|
  PROBLEM_QUERY|AUDIENCE_SPECIFIC|COMPARISON) / reason
- 先“成员派生核心词”（如 bpm finder、vocal remover），再按兼容规则加修饰词
  （free/online/ai/tool），1 条 problem query，最多 1 条 comparison
- 去重：规范化字符串 + 每个簇最多 MAX_HEAD_WORD_VARIANTS 个词头
- `build_semrush_checklist(clusters)` → 10–20 条，优先有多个产品支撑的簇

### 报告结构（Phase 2 起）
- A. Top Opportunity Clusters（簇表 + 明细 + 关键词候选）
- B. Semrush Check List（仅最高价值候选，不含 volume/KD）
- C. Individual Product Evidence（保留原有产品级评分表 + Top 5 深挖）

### 测试
- `tests/test_clustering.py`, `tests/test_keywords.py`, `tests/test_cluster_history.py`
  （Phase 2；当前共 101 个用例）

## 手工 SEO 富化 + SEO 机会分（Phase 3 新增）

### storage/enrichment_store.py + data/enrichment/
- 连接键：`cluster_id + 规范化关键词`（`record_key`）
- 必填评分字段：us_volume / global_volume / kd / weak_serp；
  可选：weak_serp_count / cpc / intent / notes（不阻塞评分）
- `upsert_metrics`：只更新传入字段；指标变化时把「旧快照」追加到 history
  （保留旧 checked_at），原子写入（tmp + os.replace）
- 状态：UNCHECKED / CHECKED / REJECTED（+ rejection_reason）
- 只增不改：历史观测永不覆盖

### scripts/enrich.py
- 交互模式（无参数）：选簇 → 选关键词 → 输入 US/Global/KD/Weak SERP
- 命令：list / list-unchecked / list-checked / list-rejected / show / set / reject
- 常用参数：`--data-dir` `--date` `--store`

### analyzers/seo_score.py
- 关键词分（0–85）= 需求(35) + KD(30) + 弱 SERP(20)，用 config/seo_weights.py 的分段表
- 簇 SEO 分（0–100）= 最强关键词分 + 支撑加成(≤6) + 长尾加成(≤9)；
  两个加成只按**不重复搜索意图**计数，重复排列不加分
- `seo_score_status`：NOT_CHECKED / PARTIAL（有数据但不够）/ VALIDATED
  （≥3 个已检查且 ≥2 个可用）
- `market_demand_gate`：PASS / WEAK / FAIL / UNKNOWN，只看 SEO 需求，
  不用产品/社区信号

### analyzers/keyword_quality.py
- 通用短语（checker tool / code editor / ai tool / productivity tool）不生成
- 无 domain 的单词簇不生成成员派生词（避免 "wa workflow enhancer"）
- 保留"tattoo generator"、"prompt generator" 这类真实头部词

### 报告
- 三个分数分开显示：Solo Builder / Cluster Evidence / SEO Opportunity
  + SEO 状态 + Market Demand Gate + 已检查关键词表（US/Global/KD/Weak/分数）
- Semrush Check List：未验证簇优先、只列 UNCHECKED、每簇 2–4 个、
  同意图不重复、总数 10–20

## 深度验证 + 最终判定（Phase 4 新增）

### analyzers/verdict.py
- 入口：`decide(cluster, store)` / `attach_verdict(clusters, store, path=..., record_history=...)`
- 维度：`substitution_risk`、`acquisition`（渠道+契合度）、`monetization`
  （模式+置信度）、`operating_cost_risk`、`competition_accessibility`
- 判定：BUILD / TEST / WATCH / SKIP；**BUILD 极难**，必须同时满足
  全部 build_requirements（见 `cluster["build_requirements"]`），否则回落 TEST/WATCH
- 硬门（分数不能覆盖）：market gate FAIL 且无非 SEO 证据、SEVERE 替代风险、
  企业直销/服务依赖、合规风险、SEVERE 成本、Solo < 50、证据整体为负
- 默认：SEO/未知渠道无需求数据 → WATCH；非 SEO 渠道但需求未证 → TEST
- `validation_gaps`：TEST/WATCH 必须给出"下一步该查什么"

### storage/validation_store.py + data/validation/
- 证据记录（类型/情感/source/url/note/summary/checked_at），URL 可选
- `verdict_history` 只增不改：previous_verdict → new_verdict + date + reason
- `current_verdicts` 用于判断是否变化（同判定不重复写）

### scripts/validate.py
- `add` / `list` / `history` / `verdicts` / `research-status`
- 手工录入即可，无需数据库

### analyzers/deep_research.py（默认关闭）
- `TREND_MONITOR_DEEP_RESEARCH=1` + 注册 provider 才会运行；
  provider 结果统一转成 evidence 记录，不会直接写进报告当事实

### 报告
- 新增 `## Top Opportunities Today`（按 verdict 排序取前 5，不强制出现 BUILD；
  没有 BUILD 会明确说明）
- 每个簇显示 Opportunity Score / Verdict / 替代风险 / 渠道与契合度 /
  变现模式与置信度 / 成本风险 / Why / Not BUILD because / Next actions /
  Verdict history

## 发现质量与关键词收紧（Phase 5 新增）

### analyzers/brand_filter.py
- 结构化品牌识别：驼峰（TattooGenie）、全大写缩写（HARPA）、字母数字混合、
  单词名（Agibot）、"Name:" 前缀（Monica: / Sider:）+ 少量常见品牌停用表
- 品牌 token 从关键词主语里剔除；`brand_tokens` / `brand_filtered_keywords`
  挂在簇上；**不要**用"只在一个成员出现"当唯一信号（会误杀 stencil/sleeve）

### analyzers/keyword_quality.py
- 成熟度：NICHE / BROAD / BRAND / AWKWARD；BRAND/AWKWARD 不生成、不进清单
- 通用短语判定改为：以填充名词结尾（ai tool / checker tool）或没有真实类别锚点
  （free checker）或锚点只是泛领域（code editor）→ generic
- 锚点：每个候选必须同时有类别锚点 + 功能锚点

### analyzers/source_quality.py
- `classify_hn_item` → PRODUCT / DEMAND_SIGNAL / NEWS_DISCUSSION / UNKNOWN
  （只有 PRODUCT 进主榜；Ask HN 只作需求证据）
- `github_product_likeness` → HIGH / MEDIUM / LOW（库/SDK/框架/研究/开发者工具
  一律 LOW，不进主榜）
- `novelty_signal` → Toolify /new 或 Show HN = HIGH；月访问百万且无增长 = LOW
- `discovery_quality` → 只用于短名单排序与过滤噪音（LOW 直接丢弃）
- `source_health` → 每个采集器 fetched / accepted / filtered / status

### collectors
- 每个 collector 暴露 `LAST_ERROR`，`collectors.source_status()` 汇总，
  报告里显示为 Source Health 的 error 列（例如 TAAFT 403）

### 报告
- 新增 `## Source Health` 表
- Semrush Check List：NICHE 优先 → 少量 BROAD 基准词（≤3）→ 每簇 1–3 个 →
  永不凑数；每行给出 "why it survived"

### 集成位置（main.py）
- 顺序：HTML 报告 → 数据存储 → indie markdown → indie HTML → 邮件发送
- indie HTML 需要传入 product_data dict（github 键对应 github_trending_data 变量）

### 导航
- `docs/index.html` 有 "View Indie Opportunities →" 链接到 `indie.html`
- `docs/indie.html` 有 "← View All Products" 链接回 `index.html`

### 输出文件
- `analysis/daily/{date}-indie.md` — markdown 报告，daily workflow 自动 commit
- `docs/indie.html` — HTML 报告，daily workflow 自动 commit

## 开发规则
- 每次修改后跑测试确认不破坏已有功能
- 新增数据源放到 collectors/ 目录
- 报告格式改动放到 reporters/ 目录
