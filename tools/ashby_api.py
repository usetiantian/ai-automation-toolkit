# -*- coding: utf-8 -*-
"""抓 Ashby 提交申请的真实 GraphQL mutation：填表 -> 提交 -> 捕获请求体"""
import sys, os, json, time, importlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import browser_form
importlib.reload(browser_form)
from browser_form import new_tab

URL = "https://jobs.ashbyhq.com/trueshort/86b5b22b-cd4d-4fda-9cd1-6d7a5bae0a6f"

# 先用公开 API 直接取 applicationForm 结构（比 CDP 抓 HTML 准）
def graphql(op, variables, query):
    import urllib.request, ssl, json as _j
    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    body = _j.dumps({"operationName": op, "variables": variables, "query": query}).encode()
    req = urllib.request.Request(
        "https://jobs.ashbyhq.com/api/non-user-graphql?op=" + op,
        data=body, headers={"Content-Type": "application/json",
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0"})
    with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
        return _j.loads(r.read().decode("utf-8", "replace"))


# 1) 用公开 posting-api 列出 trueshort 全部岗位
def get_postings(slug):
    import urllib.request, ssl
    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    u = "https://api.ashbyhq.com/posting-api/job-board/%s?includeCompensation=true" % slug
    req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


print("===== A. api.ashbyhq.com posting-api 测试 =====")
for slug in ["trueshort", "foxelligroup", "aidigest", "sleeper"]:
    try:
        d = get_postings(slug)
        jobs = d.get("jobs", [])
        print("\n--- %s : %d jobs ---" % (slug, len(jobs)))
        for j in jobs:
            print("   %-58s | %s | %s" % (str(j.get("title"))[:58],
                                          str(j.get("employmentType")),
                                          str(j.get("location"))[:40]))
            print("      url:", j.get("jobUrl"))
            print("      applyUrl:", j.get("applyUrl"))
            comp = j.get("compensation")
            if comp:
                print("      COMP:", json.dumps(comp, ensure_ascii=False)[:400])
    except Exception as e:
        print("  %s ERR %s %s" % (slug, type(e).__name__, e))

# 2) 抓 ApiJobPosting 里的 applicationForm 结构
print("\n\n===== B. applicationForm 结构（graphql） =====")
Q = """query ApiJobPosting($organizationHostedJobsPageName: String!, $jobPostingId: String!) {
  jobPosting(organizationHostedJobsPageName: $organizationHostedJobsPageName, jobPostingId: $jobPostingId) {
    title
    recaptchaAction
    applicationForm { ...FormRenderParts __typename }
  }
}
fragment FormRenderParts on Form {
  id
  label
  fields { id field { ... on FormField { id type label required } } __typename }
  __typename
}
"""
try:
    r = graphql("ApiJobPosting",
                {"organizationHostedJobsPageName": "trueshort",
                 "jobPostingId": "86b5b22b-cd4d-4fda-9cd1-6d7a5bae0a6f"}, Q)
    print(json.dumps(r, ensure_ascii=False, indent=1)[:6000])
except Exception as e:
    print("  ERR", type(e).__name__, e)
