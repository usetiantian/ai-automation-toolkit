# -*- coding: utf-8 -*-
"""
ats_harvest.py — 免key 抓取 ATS 公开岗位（Ashby / Lever / Greenhouse / Workable / SmartRecruiters / Recruitee / Personio / BambooHR）

用法:
    python ats_harvest.py boards.txt            # boards.txt 每行一个 slug
    python ats_harvest.py --probe trueshort     # 探测单个 slug 属于哪个 ATS

boards.txt 格式(每行一个):
    ashby:trueshort
    lever:somecompany
    greenhouse:figma
    workable:huggingface
"""
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
SCRATCH = Path(os.environ.get("LOCALAPPDATA", ".")) / "hermes" / "cache" / "scratch"

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
UA = "ATS-Harvester/1.0 (public job board endpoints; contact via job board operator)"

# 关键词：只看跟"代码 / AI 工程 / 安全 / 数据"沾边的岗
KEYWORDS = [
    "ai", "ml", "llm", "agent", "automation", "engineer", "developer", "sre",
    "security", "pentest", "bug bounty", "data", "backend", "frontend", "full stack",
    "full-stack", "python", "rust", "golang", "devops", "platform", "api",
    "scrap", "automation engineer", "creative technologist", "prompt",
]

WANT_TYPES = {"contract", "parttime", "part-time", "freelance", "temp", "internship"}


def get(url, timeout=12, headers=None):
    h = {"User-Agent": UA, "Accept": "application/json,text/html;q=0.9,*/*;q=0.8"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
        return r.status, r.read().decode("utf-8", "replace")


def get_json(url, timeout=12):
    st, txt = get(url, timeout)
    if st != 200:
        return None
    try:
        return json.loads(txt)
    except Exception:
        return None


def strip_html(s):
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"&[a-zA-Z#0-9]+;", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# ---------------------------------------------------------------- ATS 抓取
def ashby(slug):
    d = get_json("https://api.ashbyhq.com/posting-api/job-board/%s?includeCompensation=true" % slug)
    if not d:
        return []
    out = []
    for j in d.get("jobs", []):
        if not j.get("isListed", True):
            continue
        out.append({
            "ats": "ashby", "slug": slug, "id": j.get("id"),
            "title": j.get("title"),
            "location": j.get("location"),
            "employment_type": j.get("employmentType"),
            "workplace_type": j.get("workplaceType"),
            "department": j.get("department"),
            "published": j.get("publishedAt"),
            "url": j.get("jobUrl"),
            "apply_url": j.get("applyUrl"),
            "description": strip_html(j.get("descriptionHtml") or j.get("descriptionPlain") or "")[:1500],
            "comp": j.get("compensation") or {},
        })
    return out


def lever(slug):
    d = get_json("https://api.lever.co/v0/postings/%s?mode=json" % slug)
    if d is None:
        return []
    out = []
    for j in d if isinstance(d, list) else []:
        cat = j.get("categories") or {}
        out.append({
            "ats": "lever", "slug": slug, "id": j.get("id"),
            "title": j.get("text"),
            "location": ", ".join(cat.get("allLocations") or [cat.get("location") or ""]),
            "employment_type": cat.get("commitment"),
            "workplace_type": j.get("workplaceType"),
            "department": cat.get("department"),
            "published": j.get("createdAt"),
            "url": j.get("hostedUrl"),
            "apply_url": j.get("applyUrl"),
            "description": strip_html(j.get("descriptionPlain") or j.get("description") or "")[:1500],
            "comp": j.get("salaryRange") or {},
        })
    return out


def greenhouse(slug):
    d = get_json("https://boards-api.greenhouse.io/v1/boards/%s/jobs?content=true" % slug)
    if not d:
        return []
    out = []
    for j in d.get("jobs", []):
        loc = (j.get("location") or {}).get("name", "")
        out.append({
            "ats": "greenhouse", "slug": slug, "id": j.get("id"),
            "title": j.get("title"),
            "location": loc,
            "employment_type": "",
            "workplace_type": "",
            "department": (j.get("departments") or [{}])[0].get("name", "") if j.get("departments") else "",
            "published": j.get("updated_at"),
            "url": j.get("absolute_url"),
            "apply_url": j.get("absolute_url"),
            "description": strip_html(j.get("content") or "")[:1500],
            "comp": {},
        })
    return out


def workable(slug):
    d = get_json("https://apply.workable.com/api/v1/widget/accounts/%s?details=true" % slug)
    if not d:
        return []
    out = []
    for j in d.get("jobs", []):
        out.append({
            "ats": "workable", "slug": slug, "id": j.get("shortcode"),
            "title": j.get("title"),
            "location": ", ".join(j.get("locations") or []),
            "employment_type": j.get("employment_type"),
            "workplace_type": j.get("telecommuting"),
            "department": j.get("department"),
            "published": j.get("published_on"),
            "url": j.get("url"),
            "apply_url": j.get("application_url"),
            "description": strip_html(j.get("description") or "")[:1500],
            "comp": {},
        })
    return out


def smartrecruiters(slug):
    d = get_json("https://api.smartrecruiters.com/v1/companies/%s/postings?limit=100&offset=0" % slug)
    if not d:
        return []
    out = []
    for j in d.get("content", []):
        loc = j.get("location") or {}
        out.append({
            "ats": "smartrecruiters", "slug": slug, "id": j.get("id"),
            "title": (j.get("name") or "").strip(),
            "location": ", ".join(loc.get("city") and [loc.get("city"), loc.get("country")] or [loc.get("country", "")]),
            "employment_type": "", "workplace_type": loc.get("region", ""),
            "department": "", "published": j.get("releasedDate"),
            "url": "https://jobs.smartrecruiters.com/%s/%s" % (slug, j.get("id")),
            "apply_url": "",
            "description": strip_html((j.get("jobAd") or {}).get("sections") and
                                      json.dumps(j.get("jobAd"), ensure_ascii=False))[:1500],
            "comp": {},
        })
    return out


def recruitee(slug):
    d = get_json("https://%s.recruitee.com/api/offers/" % slug)
    if not d:
        return []
    out = []
    for j in d.get("offers", []):
        out.append({
            "ats": "recruitee", "slug": slug, "id": j.get("id"),
            "title": j.get("title"),
            "location": (j.get("location") or {}).get("city", ""),
            "employment_type": j.get("employment_type"), "workplace_type": "",
            "department": "", "published": j.get("created_at"),
            "url": j.get("careers_url") or j.get("careers_apply_url"),
            "apply_url": j.get("careers_apply_url"),
            "description": strip_html(j.get("description") or "")[:1500],
            "comp": {},
        })
    return out


def bamboo(slug):
    # BambooHR 列表端点需跟一个整数 id，改用公开 careers 页解析
    st, html = get("https://%s.bamboohr.com/jobs/" % slug)
    if st != 200:
        return []
    out = []
    for m in re.finditer(r'href="(/jobs/[^"]+)"[^>]*>([^<]{3,120})</a>', html):
        out.append({
            "ats": "bamboo", "slug": slug, "id": m.group(1),
            "title": m.group(2).strip(),
            "location": "", "employment_type": "", "workplace_type": "",
            "department": "", "published": "",
            "url": "https://%s.bamboohr.com%s" % (slug, m.group(1)),
            "apply_url": "https://%s.bamboohr.com%s" % (slug, m.group(1)),
            "description": "", "comp": {},
        })
    return out


FETCHERS = {
    "ashby": ashby, "lever": lever, "greenhouse": greenhouse,
    "workable": workable, "smartrecruiters": smartrecruiters,
    "recruitee": recruitee, "bamboo": bamboo,
}
HOST_HINTS = {
    "ashby": "jobs.ashbyhq.com", "lever": "jobs.lever.co",
    "greenhouse": "boards.greenhouse.io", "workable": "apply.workable.com",
    "smartrecruiters": "jobs.smartrecruiters.com",
    "recruitee": ".recruitee.com", "bamboo": ".bamboohr.com",
}


# ---------------------------------------------------------------- 匹配
def score(job):
    """打分：命中关键词 + 远程 + 合同制 + 有薪资 → 高分"""
    hay = ("%s %s %s %s" % (job.get("title") or "", job.get("department") or "",
                            job.get("employment_type") or "", job.get("description") or "")).lower()
    hits = [k for k in KEYWORDS if k in hay]
    if not hits:
        return 0, []
    s = len(hits) * 2
    loc = (job.get("location") or "").lower()
    if "remote" in loc or "worldwide" in loc or "anywhere" in loc:
        s += 6
    et = (job.get("employment_type") or "").lower()
    if et in WANT_TYPES:
        s += 6
    if job.get("comp"):
        s += 3
    if "ai" in hits and "video" not in hay[:400]:
        s += 2
    return s, hits


def probe(slug):
    """不知道 ATS 类型时，并发试全部 ATS；返回第一个有货的。"""
    from concurrent.futures import ThreadPoolExecutor
    order = ["ashby", "lever", "greenhouse", "workable", "smartrecruiters", "recruitee"]

    def one(a):
        try:
            return a, FETCHERS[a](slug)
        except Exception:
            return a, []

    with ThreadPoolExecutor(max_workers=len(order)) as ex:
        for a, jobs in ex.map(one, order):
            if jobs:
                return a, jobs
    return None, []


def main():
    args = sys.argv[1:]
    out_path = str(SCRATCH / "ats_jobs.json")
    if not args:
        print("usage: ats_harvest.py boards.txt | --probe slug")
        return

    if args[0] == "--probe":
        for slug in args[1:]:
            a, jobs = probe(slug)
            print("%-28s -> %-16s %d jobs" % (slug, a or "NONE", len(jobs)))
            for j in jobs[:6]:
                print("    %-52s | %-14s | %s" % (str(j["title"])[:52],
                                                j.get("employment_type"), j.get("location")))
        return

    all_jobs = []
    lines = []
    with open(args[0], encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            lines.append(line)

    from concurrent.futures import ThreadPoolExecutor

    def handle(line):
        ats, _, slug = line.partition(":")
        ats = ats.strip() or None
        slug = slug.strip()
        if not slug:
            return line, None, []
        if ats and ats in FETCHERS:
            try:
                return line, ats, FETCHERS[ats](slug)
            except Exception:
                return line, ats, []
        try:
            used, jobs = probe(slug)
        except Exception:
            used, jobs = None, []
        return line, used, jobs

    with ThreadPoolExecutor(max_workers=8) as ex:
        for line, used, jobs in ex.map(handle, lines):
            if not jobs:
                print("  %-40s -> 0 jobs" % line)
                continue
            kept = []
            for j in jobs:
                sc, hits = score(j)
                if sc:
                    j["score"] = sc
                    j["hits"] = hits
                    kept.append(j)
            kept.sort(key=lambda x: -x["score"])
            all_jobs.extend(kept)
            print("  %-40s -> %-16s %3d jobs, %2d matched" % (line, used or "-", len(jobs), len(kept)))

    all_jobs.sort(key=lambda x: -x["score"])
    json.dump(all_jobs, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\nWROTE %s  total=%d" % (out_path, len(all_jobs)))
    print("\n===== TOP 25 =====")
    for j in all_jobs[:25]:
        print("%3d | %-14s | %-46s | %-12s | %s" % (
            j["score"], j["ats"], str(j["title"])[:46],
            str(j.get("employment_type"))[:12], str(j.get("location"))[:34]))


if __name__ == "__main__":
    main()
