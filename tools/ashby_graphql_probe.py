# -*- coding: utf-8 -*-
"""探测 Ashby 免账号 GraphQL 的提交 mutation + applicationForm 结构。

目标：找到 JobApplicationSubmit / SubmitApplication 之类的 mutation，
从而实现「无浏览器直投」—— 比 CDP 点击稳定得多，且可无人值守批量跑。
"""
import json
import ssl
import urllib.request
from pathlib import Path
SCRATCH = Path(os.environ.get("LOCALAPPDATA", ".")) / "hermes" / "cache" / "scratch"

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
URL = "https://jobs.ashbyhq.com/api/non-user-graphql"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36"


def gql(op, variables, query, url=URL):
    body = json.dumps({"operationName": op, "variables": variables, "query": query}).encode()
    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/json", "User-Agent": UA,
        "Accept": "application/json", "Origin": "https://jobs.ashbyhq.com",
        "Referer": "https://jobs.ashbyhq.com/"})
    try:
        with urllib.request.urlopen(req, timeout=30, context=CTX) as r:
            return r.status, json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:600]


print("===== 1. GraphQL introspection：找 mutation 名 =====")
st, r = gql("IntrospectionQuery", {}, "query IntrospectionQuery { __schema { mutationType { fields { name } } } }")
print("status", st)
if isinstance(r, dict) and "data" in r:
    names = [f["name"] for f in (r["data"]["__schema"]["mutationType"]["fields"] or [])]
    print("mutations (%d):" % len(names))
    for n in names:
        print("   ", n)
else:
    print("introspection blocked:", str(r)[:300])

print("\n===== 2. 试常见 submit mutation（不真提交，只看错误信息） =====")
CANDIDATES = [
    "JobPostingApply", "SubmitApplication", "JobApplicationSubmit",
    "ApplicationSubmit", "SubmitJobApplication", "JobApply", "ApplyToJobPosting",
]
for op in CANDIDATES:
    st, r = gql(op, {"organizationHostedJobsPageName": "trueshort",
                     "jobPostingId": "86b5b22b-cd4d-4fda-9cd1-6d7a5bae0a6f"},
                "mutation %s { __typename }" % op)
    err = ""
    if isinstance(r, dict):
        err = (r.get("errors") or [{}])[0].get("message", "")[:110]
    else:
        err = str(r)[:110]
    print("  %-22s status=%-4s %s" % (op, st, err))

print("\n===== 3. 拉 applicationForm 完整结构（用 ApiJobPosting） =====")
Q = """query ApiJobPosting($organizationHostedJobsPageName: String!, $jobPostingId: String!) {
  jobPosting(organizationHostedJobsPageName: $organizationHostedJobsPageName, jobPostingId: $jobPostingId) {
    id
    title
    recaptchaAction
    applicationForm {
      __typename
      ... on FormRender {
        id
        label
        fields {
          __typename
          ... on FormField {
            id
            type
            label
            required
            placeholder
            helpText
          }
          ... on FormFieldGroup {
            id
            label
            required
            fields {
              __typename
              ... on FormField { id type label required placeholder helpText }
            }
          }
        }
      }
    }
  }
}"""
st, r = gql("ApiJobPosting",
            {"organizationHostedJobsPageName": "trueshort",
             "jobPostingId": "86b5b22b-cd4d-4fda-9cd1-6d7a5bae0a6f"}, Q)
print("status", st)
if isinstance(r, dict) and r.get("data"):
    jp = r["data"].get("jobPosting") or {}
    print("recaptchaAction:", jp.get("recaptchaAction"))
    af = jp.get("applicationForm") or {}
    print("form __typename:", af.get("__typename"), "| id:", af.get("id"), "| label:", af.get("label"))
    fl = af.get("fields") or []
    print("fields: %d" % len(fl))
    for f in fl:
        print("   -", json.dumps(f, ensure_ascii=False)[:260])
    json.dump(r, open(str(SCRATCH / "ashby_form_schema.json"),
                      "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\nSAVED ashby_form_schema.json")
else:
    print(str(r)[:900])
