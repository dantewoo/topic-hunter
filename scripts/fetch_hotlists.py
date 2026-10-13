#!/usr/bin/env python3
"""拉取公开热榜，作为选题热度信号。

只访问无需登录的公开页面/接口，每个源只发 1 次请求，失败即跳过，不重试、不绕过限制。
这些接口多为网页前端使用的非公开文档接口，随时可能变化；失败时按 SKILL.md 的降级路径处理。

用法：
  python3 scripts/fetch_hotlists.py                      # 全部源，每源前 30 条，紧凑文本
  python3 scripts/fetch_hotlists.py --sources weibo,baidu --limit 20
  python3 scripts/fetch_hotlists.py --format json
"""

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
TIMEOUT = 12
CST = timezone(timedelta(hours=8))


def get(url, referer=None):
    headers = {"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read().decode("utf-8", errors="replace")


def q(word):
    return urllib.parse.quote(word)


def weibo(limit):
    data = json.loads(get("https://weibo.com/ajax/side/hotSearch", referer="https://weibo.com/"))
    items = [x for x in data["data"]["realtime"] if not x.get("is_ad")]
    return [
        {
            "rank": i + 1,
            "title": x["word"],
            "heat": x.get("num"),
            "label": x.get("label_name") or "",
            "url": "https://s.weibo.com/weibo?q=" + q("#" + x["word"] + "#"),
        }
        for i, x in enumerate(items[:limit])
    ]


def baidu(limit):
    html = get("https://top.baidu.com/board?tab=realtime")
    m = re.search(r"<!--s-data:(.*?)-->", html, re.S)
    if not m:
        raise ValueError("页面结构变化，未找到 s-data")
    content = json.loads(m.group(1))["data"]["cards"][0]["content"]
    items = [x for x in content if not x.get("isTop")]  # 置顶条目不是热度排序结果
    return [
        {
            "rank": i + 1,
            "title": x["word"],
            "heat": x.get("hotScore"),
            "desc": (x.get("desc") or "")[:80],
            "url": x.get("rawUrl") or x.get("url"),
        }
        for i, x in enumerate(items[:limit])
    ]


def douyin(limit):
    data = json.loads(get("https://www.iesdouyin.com/web/api/v2/hotsearch/billboard/word/"))
    return [
        {
            "rank": i + 1,
            "title": x["word"],
            "heat": x.get("hot_value"),
            "url": "https://www.douyin.com/search/" + q(x["word"]),
        }
        for i, x in enumerate(data["word_list"][:limit])
    ]


def toutiao(limit):
    data = json.loads(get("https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc"))
    return [
        {
            "rank": i + 1,
            "title": x["Title"],
            "heat": x.get("HotValue"),
            "url": "https://www.toutiao.com/trending/%s/" % x["ClusterIdStr"]
            if x.get("ClusterIdStr")
            else x.get("Url", "").split("?")[0],
        }
        for i, x in enumerate(data["data"][:limit])
    ]


def zhihu(limit):
    data = json.loads(get("https://api.zhihu.com/topstory/hot-list?limit=50"))
    return [
        {
            "rank": i + 1,
            "title": x["target"]["title"],
            "heat": x.get("detail_text"),
            "url": "https://www.zhihu.com/question/%s" % x["target"]["id"],
        }
        for i, x in enumerate(data["data"][:limit])
    ]


def bilibili(limit):
    data = json.loads(get("https://api.bilibili.com/x/web-interface/popular?ps=%d&pn=1" % min(limit, 50)))
    if data.get("code") != 0:
        raise ValueError("接口返回 code=%s %s" % (data.get("code"), data.get("message")))
    return [
        {
            "rank": i + 1,
            "title": x["title"],
            "heat": "播放 %s" % x["stat"]["view"],
            "url": "https://www.bilibili.com/video/" + x["bvid"],
        }
        for i, x in enumerate(data["data"]["list"][:limit])
    ]


def techmeme(limit):
    root = ET.fromstring(get("https://www.techmeme.com/feed.xml"))
    out = []
    for i, it in enumerate(root.iter("item")):
        if i >= limit:
            break
        out.append(
            {
                "rank": i + 1,
                "title": re.sub(r"<[^>]+>", "", it.findtext("title") or "").strip(),
                "heat": "",
                "time": it.findtext("pubDate") or "",
                "url": it.findtext("link") or "",
            }
        )
    return out


def hackernews(limit):
    data = json.loads(get("https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage=%d" % limit))
    return [
        {
            "rank": i + 1,
            "title": x["title"],
            "heat": "%s points / %s comments" % (x.get("points"), x.get("num_comments")),
            "time": x.get("created_at", ""),
            "url": x.get("url") or "https://news.ycombinator.com/item?id=%s" % x["objectID"],
        }
        for i, x in enumerate(data["hits"][:limit])
    ]


# name: (中文名, 榜单页, 抓取函数, 圈层)
# 圈层：mass = 大众平台，可作为“出圈”信号；niche = 圈内信号，不能单独支撑热度 >= 5
SOURCES = {
    "weibo": ("微博热搜", "https://s.weibo.com/top/summary", weibo, "mass"),
    "baidu": ("百度热搜", "https://top.baidu.com/board?tab=realtime", baidu, "mass"),
    "douyin": ("抖音热榜", "https://www.douyin.com/hot", douyin, "mass"),
    "toutiao": ("今日头条热榜", "https://www.toutiao.com/", toutiao, "mass"),
    "zhihu": ("知乎热榜", "https://www.zhihu.com/hot", zhihu, "mass"),
    "bilibili": ("B站热门", "https://www.bilibili.com/v/popular/all", bilibili, "mass"),
    "techmeme": ("Techmeme", "https://www.techmeme.com/", techmeme, "niche"),
    "hackernews": ("Hacker News", "https://news.ycombinator.com/", hackernews, "niche"),
}


def run(name, limit):
    label, page, fn, tier = SOURCES[name]
    result = {"source": name, "name": label, "page": page, "tier": tier}
    try:
        result["items"] = fn(limit)
        result["ok"] = True
    except Exception as e:  # 单源失败不影响其他源
        result["ok"] = False
        result["error"] = "%s: %s" % (type(e).__name__, str(e)[:120])
    return result


def to_text(fetched_at, results):
    lines = ["抓取时间：%s（北京时间）" % fetched_at, ""]
    for r in results:
        if not r["ok"]:
            lines.append("## %s [失败] %s" % (r["name"], r["error"]))
            lines.append("")
            continue
        lines.append("## %s [%s] %s" % (r["name"], r["tier"], r["page"]))
        for x in r["items"]:
            extra = " | ".join(str(v) for v in (x.get("heat"), x.get("label"), x.get("time")) if v)
            line = "%d. %s" % (x["rank"], x["title"])
            if extra:
                line += " | " + extra
            if r["tier"] == "niche":  # 圈内源的条目链接通常就是新闻原文，保留
                line += " | " + x["url"]
            lines.append(line)
        lines.append("")
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser(description="拉取公开热榜作为热度信号")
    p.add_argument("--sources", default=",".join(SOURCES), help="逗号分隔：" + ",".join(SOURCES))
    p.add_argument("--limit", type=int, default=30, help="每个源取前 N 条，默认 30")
    p.add_argument("--format", choices=["text", "json"], default="text")
    args = p.parse_args()

    names = [s.strip() for s in args.sources.split(",") if s.strip()]
    unknown = [n for n in names if n not in SOURCES]
    if unknown:
        p.error("未知源：%s" % ",".join(unknown))

    fetched_at = datetime.now(CST).strftime("%Y-%m-%d %H:%M")
    # 每个源是不同站点，各发 1 次请求，并行只是为了省时间
    with ThreadPoolExecutor(max_workers=len(names)) as ex:
        results = list(ex.map(lambda n: run(n, args.limit), names))

    if args.format == "json":
        json.dump({"fetched_at": fetched_at, "results": results}, sys.stdout, ensure_ascii=False, indent=1)
        print()
    else:
        print(to_text(fetched_at, results))


if __name__ == "__main__":
    main()
