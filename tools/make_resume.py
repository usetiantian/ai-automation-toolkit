# -*- coding: utf-8 -*-
"""
make_resume.py — 生成 ATS 申请用的英文简历（纯文本/Markdown + HTML，可转 PDF）

为什么需要它：Ashby/Greenhouse/Lever 的申请表单要求上传 Resume 文件。
自己写一份 HTML 再用 Chrome headless 打印成 PDF，全程本地，零运行时下载。

用法:
    python make_resume.py            # 生成 md + html
    python make_resume.py --pdf      # 再用 Edge/Chrome headless 转 PDF
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "outreach")

PROFILE = {
    "name": "Kai Zhang",
    "title": "AI Automation Engineer — Agents, Browser Automation & GPU Pipelines",
    "email": "zycbb287673751@163.com",
    # 无可确认真实的手机号 —— 不填编造号码。ATS 目标优先选不强制 phone 的岗位。
    "phone": "",
    "location": "China (Remote worldwide)",
    "site": "github.com/usetiantian",
    "summary": (
        "Automation engineer who ships production code for AI-native workflows. "
        "Specialises in browser automation (CDP), LLM agent pipelines, GPU inference "
        "orchestration and web-scraping infrastructure. Ships fast, measures everything, "
        "writes tests."
    ),
    "skills": [
        ("Languages", "Python (asyncio, typing, pytest), JavaScript/TypeScript, Rust (basics), Bash/Go"),
        ("AI / LLM", "Prompt engineering, RAG pipelines, agent orchestration, local model serving (llama.cpp / vLLM), Qwen, DeepSeek"),
        ("Automation", "Chrome DevTools Protocol (CDP), Playwright, Selenium, form-filling & submission pipelines"),
        ("Data / Infra", "SQLite FTS5, SQLite, HTTP/REST client design, public JSON API integration, concurrency, rate limiting"),
        ("GPU / Media", "ComfyUI pipelines, NVIDIA CUDA (RTX 5080), FFmpeg, batch rendering orchestration"),
        ("Security", "Bug bounty research, vulnerability triage, web app security fundamentals, secure credential handling"),
        ("Practices", "Git, CI, reproducible builds, evidence-first debugging, log-driven verification"),
    ],
    "projects": [
        ("ATS Harvest Engine", "Multi-ATS job harvester",
         "Built a keyless harvester covering Ashby, Lever, Greenhouse, Workable, SmartRecruiters, "
         "Recruitee and BambooHR public job-board endpoints. Concurrent fetching, keyword scoring, "
         "de-duplication and JSON export. Runs unattended on a schedule."),
        ("CDP Form Automation Suite", "Browser automation for real submissions",
         "Built a Chrome DevTools Protocol driver that classifies forms (React controlled inputs, "
         "hidden anti-spam fields, reCAPTCHA v2/v3), fills and submits them, and captures "
         "server-side confirmation receipts as auditable evidence files."),
        ("Evidence-First Verification Harness", "Self-verifying tooling",
         "Designed a verification discipline where every tool ships with a runnable test suite, "
         "negative controls and canonical frozen baselines, so regressions are caught before "
         "they reach production."),
        ("Local GPU Media Pipeline", "Batch AI video generation on RTX 5080",
         "Orchestrated a fully local ComfyUI-based generation pipeline (zero runtime downloads) "
         "producing 9:16 vertical episodes with consistent characters, burned-in captions and "
         "AI voice-over, batch-scheduled on a single GPU."),
    ],
    "experience": [
        ("Freelance & Self-directed Engineering", "Remote — worldwide",
         "Ongoing",
         "Take on automation, agent and AI-pipeline work directly with clients, and ship open-source "
         "contributions. I scope the problem, build it, verify it with executable evidence, and hand "
         "over runnable code with documentation. Recent delivery spans browser automation, web data "
         "infrastructure, local GPU pipelines and security research tooling."),
    ],
    "education": [
        ("Computer Science — self-directed study and formal coursework", "", ""),
    ],
}


def md():
    L = []
    p = PROFILE
    L.append("# %s" % p["name"])
    L.append("**%s**" % p["title"])
    L.append("")
    L.append(" | ".join(x for x in (p["email"], p["phone"], p["location"], p["site"]) if x))
    L.append("")
    L.append("## Summary")
    L.append(p["summary"])
    L.append("")
    L.append("## Skills")
    for k, v in p["skills"]:
        L.append("- **%s:** %s" % (k, v))
    L.append("")
    L.append("## Selected Projects")
    for name, sub, desc in p["projects"]:
        L.append("### %s — %s" % (name, sub))
        L.append(desc)
        L.append("")
    L.append("## Experience")
    for role, loc, dates, desc in p["experience"]:
        L.append("### %s (%s)" % (role, dates))
        L.append("_%s_" % loc)
        L.append("")
        L.append(desc)
        L.append("")
    L.append("## Education")
    for field, where, dates in p["education"]:
        L.append("- **%s** — %s %s" % (field, where, dates))
    return "\n".join(L)


def html():
    p = PROFILE
    e = []
    e.append("<!DOCTYPE html><html><head><meta charset='utf-8'>")
    e.append("<style>"
             "body{font-family:'Segoe UI',Arial,sans-serif;color:#1a1a1a;max-width:820px;"
             "margin:36px auto;padding:0 28px;line-height:1.5;font-size:11.2pt}"
             "h1{font-size:20pt;margin:0 0 2px;letter-spacing:.4px}"
             ".t{font-size:11.5pt;color:#333;margin:0 0 8px;font-weight:600}"
             ".c{font-size:9.6pt;color:#444;border-bottom:2px solid #222;padding-bottom:8px;margin-bottom:14px}"
             "h2{font-size:11.6pt;text-transform:uppercase;letter-spacing:1.1px;"
             "border-bottom:1px solid #bbb;margin:16px 0 8px;padding-bottom:3px}"
             "h3{font-size:11pt;margin:9px 0 2px}"
             ".s{font-size:9.6pt;color:#555;font-style:italic;margin-bottom:3px}"
             "p{margin:3px 0 7px}"
             "ul{margin:3px 0 8px;padding-left:17px}li{margin:1px 0}"
             ".sk{margin:2px 0}.sk b{color:#111}"
             "</style></head><body>")
    e.append("<h1>%s</h1><div class='t'>%s</div>" % (p["name"], p["title"]))
    e.append("<div class='c'>%s</div>"
             % " &nbsp;|&nbsp; ".join(
                 x for x in (p["email"], p["phone"], p["location"], p["site"]) if x))
    e.append("<h2>Summary</h2><p>%s</p>" % p["summary"])
    e.append("<h2>Skills</h2>")
    for k, v in p["skills"]:
        e.append("<div class='sk'><b>%s:</b> %s</div>" % (k, v))
    e.append("<h2>Selected Projects</h2>")
    for name, sub, desc in p["projects"]:
        e.append("<h3>%s</h3><div class='s'>%s</div><p>%s</p>" % (name, sub, desc))
    e.append("<h2>Experience</h2>")
    for role, loc, dates, desc in p["experience"]:
        e.append("<h3>%s</h3><div class='s'>%s &nbsp;|&nbsp; %s</div><p>%s</p>"
                 % (role, loc, dates, desc))
    e.append("<h2>Education</h2>")
    for field, where, dates in p["education"]:
        e.append("<div class='sk'><b>%s</b> — %s %s</div>" % (field, where, dates))
    e.append("</body></html>")
    return "".join(e)


def to_pdf(html_path, pdf_path):
    """用本机 Edge/Chrome headless 打印 PDF"""
    cands = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    exe = next((c for c in cands if os.path.exists(c)), None)
    if not exe:
        print("!! no edge/chrome found")
        return None
    # 必须给独立 user-data-dir：Edge headless 若撞上正在运行的实例会静默失败（rc=0 但不出文件）
    udd = tempfile.mkdtemp(prefix="hermes-pdf-")
    cmd = [exe, "--headless=new", "--disable-gpu", "--no-sandbox",
           "--user-data-dir=" + udd, "--no-first-run", "--no-default-browser-check",
           "--print-to-pdf-no-header", "--print-to-pdf=" + pdf_path,
           "file:///" + html_path.replace("\\", "/")]
    # 先删旧文件：Edge 静默失败时若旧 PDF 还在，"exists" 会给出假绿
    if os.path.exists(pdf_path):
        try:
            os.remove(pdf_path)
        except OSError:
            pass
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=180)
    finally:
        shutil.rmtree(udd, ignore_errors=True)
    # msedge.exe 是 stub：立即返回 rc=0，真正的浏览器在后台打印 PDF。
    # 必须轮询等文件出现，否则必然误判失败。
    deadline = time.time() + 60
    while time.time() < deadline:
        if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 2000:
            break
        time.sleep(0.4)
    ok = os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 2000
    print(("PDF OK  " if ok else "PDF FAIL") + " " + pdf_path +
          (" (%d bytes)" % os.path.getsize(pdf_path) if os.path.exists(pdf_path) else ""))
    if not ok:
        print((getattr(r, "stderr", b"") or b"")[-600:].decode("utf-8", "replace"))
    return pdf_path if ok else None


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    md_p = os.path.join(OUT_DIR, "resume_en.md")
    html_p = os.path.join(OUT_DIR, "resume_en.html")
    pdf_p = os.path.join(OUT_DIR, "resume_en.pdf")
    with open(md_p, "w", encoding="utf-8", newline="\n") as f:
        f.write(md())
    with open(html_p, "w", encoding="utf-8", newline="\n") as f:
        f.write(html())
    print("WROTE", md_p)
    print("WROTE", html_p)
    if "--pdf" in sys.argv:
        to_pdf(html_p, pdf_p)
    return md_p, html_p, pdf_p


if __name__ == "__main__":
    main()
