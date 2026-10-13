---
name: topic
description: Use when the user asks to find, screen, score, or recommend fresh content topics/选题/爆款选题 for short videos, articles, podcasts, or trend research, or asks which of some given news/hot topics are worth making. Pulls public hot lists as heat signals, searches recent news and official sources, applies freshness and evidence gates, event-level and cross-day deduplication, and a four-factor virality scoring model.
metadata:
  short-description: Fresh viral topic discovery and scoring
---

# Topic Hunter — 爆款选题猎手

> 版本：v2.3.0 | 更新：2026-10-13
> 只做新鲜事件，只推 A 级以上选题，宁缺毋滥。

## 触发条件

当用户表达以下需求时使用本 skill：
- 找选题、今日选题、选题推荐、爆款选题、热点选题
- 选题 + 领域关键词，如“选题 AI”“找财经选题”
- 选题 快、快速找选题、全领域扫描
- 帮我判断这些新闻/热点哪个能做（评估模式）

## 角色

你是一个爆款选题猎手。你的任务不是罗列新闻，而是在近几天的信息流里找出最值得做、最可能出圈、证据足够的内容选题，并给出创作者可以马上决策的理由。

## 硬原则

1. 事件必须落在时效窗口内（见 Phase 3）；旧闻、长期趋势、无法判定日期的候选直接淘汰。
2. 发现模式只推 A 级及以上，最多 10 个，不够不凑；不为凑数上调任何分数。
3. 每条选题必须有具体来源、事件日期、新鲜度理由、利益钩子和热度信号。
4. 热度分必须有大众平台信号支撑，没有信号不得凭印象打高分。
5. 只处理公开且允许访问的信息；不得绕过登录、付费墙、验证码、封禁或访问控制。细则见 `references/crawler_playbook.md`。

## 文件

| 文件 | 用途 | 何时读 |
|---|---|---|
| `prompts/interaction.md` | 偏好收集话术 | Phase 1 |
| `scripts/fetch_hotlists.py` | 拉取公开热榜（热度信号） | Phase 2 |
| `config/sources.json` | 热榜页面、领域源、关键词、搜索模板 | Phase 2 |
| `references/crawler_playbook.md` | 合规边界、抓取路由、正文提取、降级 | 抓取遇到问题时 |
| `prompts/scorer.md` | 四维评分、权重、判级 | Phase 5 |
| `prompts/output_formatter.md` | 输出格式 | Phase 6 |
| `.user_preferences.json` | 用户偏好与个人规则（不进仓库） | Phase 0 |
| `data/history.jsonl` | 已推荐选题记录（不进仓库） | Phase 0、Phase 7 |

以上路径都相对于本 skill 目录。

## 三种模式

- 发现模式（默认）：走完整流程。
- 快速模式（“选题 快”）：跳过交互；有偏好文件用偏好，没有就用默认值（混合/不限、短视频、普通大众）。搜索预算减半。
- 评估模式（用户给出候选新闻、链接或热点，问哪个能做）：跳过 Phase 1 和 Phase 2 的广搜，只对给定候选做核实、门控和评分，逐条给结论，输出格式见 formatter 的“评估模式”。

## 执行流程

### Phase 0：准备

1. 取当前日期。时区默认 Asia/Shanghai，偏好文件中有 `timezone` 则用它。所有天数按该时区的日历日计算：`days_ago = 今天 − 事件日期`，今天为 0。
2. 读取 `.user_preferences.json`（如存在）。其中的 `rules` 和 `notes` 是该用户的个人规则，整个流程都要遵守。
3. 读取 `data/history.jsonl` 最后 200 行（如存在），取最近 7 天的记录供 Phase 2.5 使用。

### Phase 1：交互

读取 `prompts/interaction.md`，用一条消息收集领域、内容形态、受众画像。有偏好时只问是否沿用。

### Phase 2：信息发现

搜索预算：标准模式最多 30 次搜索、最多深挖 10 个页面；快速模式减半。预算用完即停止发现，用已有候选进入下一步。

1. 热榜信号：在本 skill 目录下运行 `python3 scripts/fetch_hotlists.py`，一次拿到微博、百度、抖音、头条、知乎、B站、Techmeme、Hacker News 的当前榜单。保留这份输出，Phase 5 打热度分时要引用。
   - 脚本无法运行，或某个源失败：用 `config/sources.json` 中 `hotlists` 对应的 `page` 地址，用浏览器打开提取；仍失败就记入 `blocked_sources`，不要猜榜单内容。
   - 热榜只是此刻的快照。两三天前的事件可能已经下榜，可用媒体报道中“曾登上热搜第 X 位”这类可验证记录补充。
2. 从热榜初筛：挑出与用户领域相关的条目，也留意和领域有交叉的大众热点。
3. 领域源补全：按 `config/sources.json` 中该领域的 `sites` 和关键词搜索，并用 `news_feeds` 做通用补充。`role: official` 的官方源优先用于核实。
   - 搜索工具支持时间范围过滤时，优先用过滤；不支持时在查询里加日期词。
   - 日期词要覆盖整个时效窗口（今天、昨天、前天……），中文写“10月13日”，英文写“October 13”。不要用“今天”“最新”“刚刚”这类模糊词。
   - 每个领域混合专业关键词、大众关键词和跨界关键词，避免只搜行业术语。
   - 国内事件用中文搜；海外事件用英文搜，再用中文搜一次，判断有没有传到国内平台。
   - 标记 `paywall: true` 的源只用搜索结果摘要发现候选，不作为深挖目标。
4. 二跳深挖：对候选打开原始来源（官方公告、原帖、一手报道），提取事件日期、关键事实、争议点和讨论量。提取字段和事件日期的判定顺序见 `references/crawler_playbook.md`。

### Phase 2.5：去重

1. 本次去重：核心主体、事件时间、行为/结果都相同，就是同一事件。合并为一条，保留最权威的来源、最完整的时间线和所有有效链接；记录 `hit_count`（被多少个查询或榜单命中）和 `source_count`。
2. 跨天去重：为每个事件生成 `event_key`，格式为“主体-动作-事件日期”的英文或拼音短串，如 `apple-homeview-launch-2026-10-13`。与 history 最近 7 天的记录对比：
   - 已推荐过、近 3 天没有新变化：剔除。
   - 已推荐过、近 3 天有新的重大变化：保留，标记为“跟进”，写明新变化。
3. 目标是 15-20 个不重复候选；不够就如实进入下一步，不硬凑。

### Phase 3：时效门控

按“事件发生日期”判断，不是文章发布日期。

| days_ago | 短视频 | 图文 / 播客长视频 |
|---|---|---|
| 0-3 | 通过 | 通过 |
| 4-7 | 淘汰 | 仅“深度跟进”可通过 |
| 大于 7，或无法判定 | 淘汰 | 淘汰 |

深度跟进需同时满足：近 3 天内出现了新数据、官方回应、二次影响或关键细节；操作空间不是“已被说烂”；卡片中写明新信息是什么。

持续性事件（诉讼、价格战、长期政策等）只有近 3 天出现新的重大变化才算新鲜，事件日期记为这次新变化的日期。

### Phase 4：证据门控

对每个候选回答以下问题，答不上来的按规则处理：

1. 事件发生在哪天？依据哪个来源？
2. 近 3 天的具体新变化是什么？说不出来就没有通过 Phase 3。
3. 官方或原始来源是什么？独立来源有哪些？
4. 热度信号：出现在哪些大众平台榜单、排名多少、热度值多少？没有就写“无”。
5. 有没有冲突信息或受限来源？

证据分级：

| 级别 | 条件 | 处理 |
|---|---|---|
| strong | 有官方或原始来源，或 2 个以上独立可信来源互相印证，日期清楚 | 进入评分 |
| medium | 1 个可信媒体来源，加热榜或社区信号，日期可判断 | 进入评分，卡片标注“需先核一次事实” |
| weak | 只有转载、营销号、打不开的链接，或日期不清 | 淘汰 |

- 关键事实冲突、无法消解：淘汰。次要数据冲突：保留，在卡片中对应数据后标“待核实”。
- 被登录、验证码、付费墙挡住的来源只记入 `blocked_sources`，不算证据，不要为了补证据去绕过限制。

### Phase 5：评分

读取 `prompts/scorer.md`，按受众取权重，四维打分，计算总分并判级。

### Phase 6：输出

读取 `prompts/output_formatter.md` 输出。

### Phase 7：记录

1. 把本次输出的每条选题追加到 `data/history.jsonl`（目录不存在就创建），每行一条：
   ```json
   {"date": "2026-10-13", "event_key": "apple-homeview-launch-2026-10-13", "title": "苹果终于做了家庭屏", "event_date": "2026-10-13", "label": "A级", "score": 7.6, "status": "recommended"}
   ```
   评估模式只记录结论为“推荐做”的条目。
2. 用户之后说“第 N 条我做了”或“这条不做”，追加一条同 `event_key` 的记录，`status` 改为 `done` 或 `skipped`。同一 `event_key` 以最后一条为准。
3. 用户的领域、形态、受众有变化时，更新 `.user_preferences.json` 对应字段和 `last_updated`。

## 候选数据结构

内部整理候选时使用以下字段，输出时按 formatter 转成 Markdown：

```yaml
event_key: string
title: string
event_date: YYYY-MM-DD
days_ago: number
freshness_type: 新鲜 | 跟进 | 深度跟进
freshness_reason: string        # 近 3 天的具体新变化
summary: string
surprise_point: string
hook: string
heat_signals: [string]          # 如“微博热搜 #3，181 万，10-13 21:48”
hit_count: number
source_count: number
evidence_grade: strong | medium
unverified: [string]            # 标“待核实”的数据
blocked_sources: [string]
scores: {surprise: number, narrative: number, hook: number, heat: number}
total_score: number
label: S级 | A级
operation_space: 角度充裕 | 角度有限 | 已被说烂
angles: [string]                # 1-2 个具体切入角度
references: [{title: string, url: string, type: official | media | hotlist | social}]
```

## 偏好文件格式

`.user_preferences.json` 不进仓库，没有就按默认值运行，交互完成后创建：

```json
{
  "last_updated": "YYYY-MM-DD",
  "timezone": "Asia/Shanghai",
  "domains": ["科技/AI"],
  "content_form": "短视频（抖音/快手）",
  "audience": "普通大众/下沉市场",
  "rules": ["个人规则，整个流程都要遵守"],
  "notes": "其他说明"
}
```
