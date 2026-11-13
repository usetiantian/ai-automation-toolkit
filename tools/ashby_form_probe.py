# -*- coding: utf-8 -*-
"""抓 Ashby 申请页的完整表单结构：CDP 抓原始 query + 用原始 query 拿 applicationForm JSON"""
import sys, os, json, time, importlib, re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import browser_form
importlib.reload(browser_form)
from browser_form import new_tab
from pathlib import Path
SCRATCH = Path(os.environ.get("LOCALAPPDATA", ".")) / "hermes" / "cache" / "scratch"

APPLY = "https://jobs.ashbyhq.com/trueshort/86b5b22b-cd4d-4fda-9cd1-6d7a5bae0a6f/application"

p, tid = new_tab(url="about:blank")
try:
    p.send("Network.enable", {})
    p.send("Page.enable", {})
    p.goto(APPLY, wait=20)
    time.sleep(6)

    # 找 Network.requestWillBeSent 里 ApiJobPosting 的完整 postData
    full = None
    for ev in p.events:
        if ev.get("method") != "Network.requestWillBeSent":
            continue
        rq = ev.get("params", {}).get("request", {})
        pd = rq.get("postData") or ""
        if "ApiJobPosting" in pd and len(pd) > len(full or ""):
            full = pd
    if not full:
        print("!! no ApiJobPosting request captured")
    else:
        print("captured postData len =", len(full))
        body = json.loads(full)
        print("operationName =", body.get("operationName"))
        print("variables =", json.dumps(body.get("variables")))
        q = body.get("query", "")
        print("\n===== FULL QUERY (%d chars) =====\n%s" % (len(q), q))
        open(str(SCRATCH / "ashby_query.txt"),
             "w", encoding="utf-8").write(q)

        # 直接用这个 query 再请求一次，拿完整 applicationForm
        import urllib.request, ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(
            "https://jobs.ashbyhq.com/api/non-user-graphql?op=ApiJobPosting",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0"})
        with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
            resp = json.loads(r.read().decode("utf-8", "replace"))
        open(str(SCRATCH / "ashby_form.json"),
             "w", encoding="utf-8").write(json.dumps(resp, ensure_ascii=False, indent=1))
        jp = (resp.get("data") or {}).get("jobPosting") or {}
        print("\n===== jobPosting keys =====")
        print(sorted(jp.keys()))
        af = jp.get("applicationForm")
        print("\n===== applicationForm (raw, 4000) =====")
        print(json.dumps(af, ensure_ascii=False, indent=1)[:4000])
        print("\nrecaptchaAction =", jp.get("recaptchaAction"))
finally:
    try:
        p.close()
    except Exception:
        pass
