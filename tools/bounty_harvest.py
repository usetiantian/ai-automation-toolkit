# -*- coding: utf-8 -*-
"""
bounty_harvest.py — PR 赏金猎手（GitHub 公共 API，免 key / 免登录）

为什么做这个：
    ATS 岗位数据（2301 条）实测全是巨头（OpenAI/Palantir/Ramp/Notion），
    对没有海外工作履历的候选人转化率≈0。
    PR 赏金是另一条通道：**不需要过招聘筛**，只要 PR 被合并就付钱，
    且付款走加密货币/平台钱包，不需要邮箱验证码。

数据源：
    GitHub Search API（未认证 60 req/h，Search 10 req/min）
    金额在 **标签名** 里：Algora 约定 `💎 Bounty $5000`；Polar 同样。

用法：
    python bounty_harvest.py                     # 抓 + 打分 + 打印 top
    python bounty_harvest.py --out bounties.json  # 落盘
    python bounty_harvest.py --min 1000         # 只看 >=$1000
    python bounty_harvest.py --repo openai/codex  # 只看某个仓库
"""
import argparse
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# 技术栈匹配度：命中越多越贴合我这台机器（Python/Node/Rust/Go/浏览器自动化）
STACK = {
    "python": 3, "typescript": 3, "javascript": 2, "node": 2, "rust": 2,
    "golang": 1, "go ": 1, "typescript": 3, "react": 1, "browser": 3,
    "playwright": 3, "puppeteer": 3, "selenium": 2, "scrap": 3, "crawl": 3,
    "api": 2, "sdk": 2, "cli": 2, "docs": 2, "test": 2, "lint": 1,
    "agent": 3, "llm": 3, "ai ": 2, "pipeline": 2, "workflow": 2, "webhook": 2,
}
# 负面：这些活儿不是"代码+思考力"能交付的
NEG = ("design", "illustration", "video edit", "thumbnail", "marketing copy",
       "seo ", "social media", "customer support", "sales ", "recruit")
# 已被抢的信号：评论多 = 竞争激烈
COMPETITION_WEIGHT = 6.0


def _get(url, headers=None, timeout=30):
    h = {"User-Agent": UA, "Accept": "application/vnd.github+json"}
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def search_issues(label, per_page=100, max_pages=10, extra=""):
    """分页翻 GitHub Search。未认证 Search 限速 10/min，页间必须等。"""
    out, seen = [], set()
    for page in range(1, max_pages + 1):
        q = urllib.parse.quote('label:"%s" state:open %s' % (label, extra))
        url = "https://api.github.com/search/issues?q={}&per_page={}&page={}".format(q, per_page, page)
        try:
            d = _get(url)
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                print("  [rate-limit] 等待 65s...", file=sys.stderr)
                time.sleep(65)
                continue
            print("  [search error]", e.code, str(e)[:120], file=sys.stderr)
            break
        items = d.get("items") or []
        if not items:
            break
        for it in items:
            if it["html_url"] in seen:
                continue
            seen.add(it["html_url"])
            out.append(it)
        if len(out) >= (d.get("total_count") or 0):
            break
        time.sleep(7)   # 未认证 search 10 req/min
    return out


AMT_RE = re.compile(r"\$\s*([\d,]+(?:\.\d+)?)\s*([kKmM]?)")


def parse_amount(labels, title, body):
    """金额优先取标签名（Algora 约定），其次标题，最后正文。"""
    for src in (labels, [title], [body or ""]):
        for s in src:
            m = AMT_RE.search(s or "")
            if m:
                v = float(m.group(1).replace(",", ""))
                suf = m.group(2).lower()
                if suf == "k":
                    v *= 1000
                elif suf == "m":
                    v *= 1_000_000
                if v > 0:
                    return v
    return 0.0


def apply_trust_filters(rows):
    """把"赏金农场"过滤掉。

    实测教训（2026-11-13）：只按金额排序会被三个 AI 诱饵仓库骗到——
      lizTheDeveloper/privacy-the-game   377 个 issue，最大标 $1,043,316
      ClankerNation/OpenAgents           201 个 issue，标签写死 "AI only allowed - no humans"
      UnsafeLabs/Bounty-Hunters          182 个 issue，标签 "AI Agent friendly"
    它们专门批量刷 issue、贴巨额假奖金，骗自动化代理白干。
    三条硬过滤（都不需要额外 API 配额）：
      1) 同一仓库 issue 数量 >= MAX_PER_REPO  -> 批量刷的，整仓丢
      2) 出现"只允许 AI / AI 友好"这类标签 -> 明确针对自动化的诱饵
      3) 全部 issue 在 BURST_DAYS 天内刷出 -> 一次性倾泻
    """
    MAX_PER_REPO = 10
    BURST_DAYS = 14
    BAIT = ("ai only allowed", "ai agent friendly", "autonomus agents only",
            "no humans", "agents only", "ai agents only")
    byrepo = {}
    for r in rows:
        byrepo.setdefault(r["repo"], []).append(r)

    dropped = {}
    for repo, rs in byrepo.items():
        if len(rs) >= MAX_PER_REPO:
            dropped[repo] = "issue 数量 %d >= %d（批量刷）" % (len(rs), MAX_PER_REPO)
            continue
        bait = [l for r in rs for l in r["labels"]
                if any(b in l.lower() for b in BAIT)]
        if bait:
            dropped[repo] = "诱饵标签 %s" % sorted(set(bait))[:2]
            continue
        ts = [r["created"] for r in rs if r.get("created")]
        if len(ts) >= 3:
            try:
                t0 = min(datetime.strptime(x, "%Y-%m-%dT%H:%M:%SZ") for x in ts)
                t1 = max(datetime.strptime(x, "%Y-%m-%dT%H:%M:%SZ") for x in ts)
                if (t1 - t0).days < BURST_DAYS:
                    dropped[repo] = "%d 天内批量刷出" % (t1 - t0).days
                    continue
            except Exception:
                pass
    kept = [r for r in rows if r["repo"] not in dropped]
    return kept, dropped


def score(item, amount):
    repo = item["repository_url"].split("/repos/")[-1]
    title = item.get("title") or ""
    body = item.get("body") or ""
    low = (title + " " + body).lower()
    labels = [l["name"] for l in item.get("labels") or []]

    s = 0.0
    s += min(amount, 10000) / 500.0            # 金额贡献，封顶 20
    for k, w in STACK.items():
        if k in low:
            s += w
    for k in NEG:
        if k in low:
            s -= 6
    s -= item.get("comments", 0) * COMPETITION_WEIGHT / 3.0   # 评论=竞争
    if any("good first issue" in l.lower() for l in labels):
        s += 8                                   # 新手友好
    if "help wanted" in low:
        s += 3
    # 金额写在标签里 = 平台（Algora/Polar）程序化创建，比标题里手写的更可信
    if any("$" in l for l in labels):
        s += 6
    return s


def repo_meta(repo_full):
    try:
        return _get("https://api.github.com/repos/" + repo_full, timeout=20)
    except Exception:
        return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "..", "outreach", "bounties.json"))
    ap.add_argument("--min", type=float, default=0.0, help="只看 >= $N")
    ap.add_argument("--repo", default="", help="只看某仓库，如 openai/codex")
    ap.add_argument("--labels", default="💎 Bounty,Bounty")
    ap.add_argument("--max-pages", type=int, default=10)
    a = ap.parse_args()

    items = []
    for lab in a.labels.split(","):
        lab = lab.strip()
        if not lab:
            continue
        print("== 扫描标签:", lab, file=sys.stderr)
        items += search_issues(lab, max_pages=a.max_pages)
    # 去重
    byurl = {it["html_url"]: it for it in items}
    items = list(byurl.values())
    print("抓到 issues:", len(items), file=sys.stderr)

    rows = []
    for it in items:
        repo = it["repository_url"].split("/repos/")[-1]
        if a.repo and repo.lower() != a.repo.lower():
            continue
        labels = [l["name"] for l in it.get("labels") or []]
        amt = parse_amount(labels, it.get("title"), it.get("body"))
        if amt < a.min:
            continue
        rows.append({
            "amount": amt,
            "repo": repo,
            "title": it.get("title"),
            "url": it["html_url"],
            "labels": labels,
            "comments": it.get("comments", 0),
            "created": it.get("created_at"),
            "updated": it.get("updated_at"),
            "body_head": (it.get("body") or "")[:1200],
            "score": round(score(it, amt), 2),
        })
    rows, dropped = apply_trust_filters(rows)
    rows.sort(key=lambda r: -r["score"])
    print("信任过滤：丢弃 %d 个赏金农场仓库（%s）" % (
        len(dropped), ", ".join("%s(%s)" % (k, v) for k, v in list(dropped.items())[:6])), file=sys.stderr)
    out = os.path.abspath(a.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump(rows, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("WROTE %s (%d 条)" % (out, len(rows)), file=sys.stderr)
    for r in rows[:40]:
        print("  $%-8.0f  %-38s  %-52s  c=%-3d  %.1f" % (
            r["amount"], r["repo"][:38], (r["title"] or "")[:52], r["comments"], r["score"]))
    print("总金额池: $%.0f" % sum(r["amount"] for r in rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
