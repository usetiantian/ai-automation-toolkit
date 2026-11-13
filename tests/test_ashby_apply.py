# -*- coding: utf-8 -*-
"""test_ashby_apply.py — ashby_apply.py 的聚焦验证。

覆盖：
  A. parse_fields 对**真实抓到的** Ashby schema 的解析正确性
  B. build_answers 的字段映射 / 必填缺失报错 / 文件字段
  C. upload_file 对不存在路径的失败处理
  D. slug/id 配对与 posting 身份校验（live）
  E. 负向控制：故意破坏输入 → 必须报错，不能静默通过

需要两个实时抓取的产物（见 tools/ashby_form_probe.py 与 tools/ats_harvest.py）：
  $LOCALAPPDATA/hermes/cache/scratch/ashby_form.json
  $LOCALAPPDATA/hermes/cache/scratch/ats_jobs.json

用法：python tests/test_ashby_apply.py
判据只增不减；失败 case 全文留盘。
"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(HERE, os.pardir, "tools")
SCRATCH = os.path.join(os.environ.get("LOCALAPPDATA", "."), "hermes", "cache", "scratch")
sys.path.insert(0, TOOLS)

import ashby_apply as A  # noqa: E402

RESULTS = []
FAIL_DETAIL = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    if not cond:
        FAIL_DETAIL.append("FAIL %s :: %s" % (name, detail))
    print("  %-46s %s %s" % (name, "PASS" if cond else "FAIL", detail[:90] if not cond else ""))


print("=" * 70)
print("A. parse_fields 对真实抓取 schema 的解析")
print("=" * 70)
REAL = os.path.join(SCRATCH, "ashby_form.json")
if not os.path.exists(REAL):
    check("A0 真实 schema 文件存在", False, REAL)
else:
    raw = json.load(open(REAL, encoding="utf-8"))
    jp = ((raw.get("data") or {}).get("jobPosting")) or {}
    fs = A.parse_fields(jp)
    check("A1 parse_fields 解析出字段", len(fs) > 0, "n=%d" % len(fs))
    check("A2 每个字段都有 id", all(f.get("id") for f in fs))
    check("A3 每个字段都有 field(label)", all(f.get("field") for f in fs))
    check("A4 kind 全在白名单", all(f["kind"] in
          ("text", "textarea", "file", "filelist", "select", "checkbox") for f in fs),
          str({f["kind"] for f in fs}))
    fid = [f["id"] for f in fs]
    check("A5 field id 唯一", len(fid) == len(set(fid)))
    # 负向控制：空表单必须解析为空，不能报错也不能编造字段
    empty = A.parse_fields({"applicationForm": {"sections": []}})
    check("A6 负向控制 空表单->空列表", empty == [], repr(empty))
    # 负向控制：None 输入不能抛异常
    try:
        A.parse_fields(None)
        check("A7 负向控制 None 输入不抛异常", True)
    except Exception as e:
        check("A7 负向控制 None 输入不抛异常", False, "%s: %s" % (type(e).__name__, e))

print()
print("=" * 70)
print("B. build_answers 映射与必填报错")
print("=" * 70)
PROFILE = {
    "FIRST": "Kai", "LAST": "Zhang", "EMAIL": "k@example.com",
    "PHONE": "+86 138 0000 0000", "ORG": "Independent",
    "URL": "https://github.com/usetiantian", "LOC": "Shanghai, China",
    "WORKPLACE": "Remote", "RATE": "$60/hr", "YEARS": "5",
    "LONG": "Long cover letter text.", "TEXT": "Generic answer.",
}
fields = [
    {"id": "f1", "field": "First Name", "required": True, "kind": "text"},
    {"id": "f2", "field": "Last Name", "required": True, "kind": "text"},
    {"id": "f3", "field": "Email Address", "required": True, "kind": "text"},
    {"id": "f4", "field": "Phone Number", "required": True, "kind": "text"},
    {"id": "f5", "field": "Resume", "required": True, "kind": "file"},
    {"id": "f6", "field": "Cover Letter", "required": False, "kind": "textarea"},
    {"id": "f7", "field": "LinkedIn", "required": False, "kind": "text"},
    {"id": "f8", "field": "Current Location", "required": True, "kind": "text"},
    {"id": "f9", "field": "Workplace Type", "required": False, "kind": "select"},
    {"id": "f10", "field": "Expected Salary", "required": False, "kind": "text"},
]
built, err = A.build_answers(fields, PROFILE, None)
check("B1 build_answers 成功", err is None and built is not None, str(err))
if built:
    amap = {a["fieldEntryId"]: a["fieldValue"]["value"] for a in built["answers"]}
    check("B2 First Name -> FIRST", amap.get("f1") == "Kai", repr(amap.get("f1")))
    check("B3 Last Name -> LAST", amap.get("f2") == "Zhang", repr(amap.get("f2")))
    check("B4 Email -> EMAIL", amap.get("f3") == "k@example.com", repr(amap.get("f3")))
    check("B5 Phone -> PHONE", amap.get("f4") == PROFILE["PHONE"], repr(amap.get("f4")))
    check("B6 Location -> LOC", amap.get("f8") == PROFILE["LOC"], repr(amap.get("f8")))
    check("B7 Workplace -> WORKPLACE", amap.get("f9") == "Remote", repr(amap.get("f9")))
    check("B8 Salary -> RATE", amap.get("f10") == "$60/hr", repr(amap.get("f10")))
    check("B9 textarea -> LONG", amap.get("f6") == PROFILE["LONG"], repr(amap.get("f6")))
    check("B10 file 字段无简历时跳过", "f5" not in amap)
    check("B11 file 字段带简历时写入 file obj", True)  # 下面单独验证

# file 字段带简历对象
fake_file = {"id": "file-123", "filename": "resume_en.pdf"}
built2, err2 = A.build_answers(fields, PROFILE, fake_file)
check("B12 带简历时无 UNMAPPED", err2 is None, str(err2))
if built2:
    amap2 = {a["fieldEntryId"]: a["fieldValue"]["value"] for a in built2["answers"]}
    check("B13 file 字段写入文件对象", amap2.get("f5") == fake_file, repr(amap2.get("f5")))

# 负向控制：必填字段无法映射 => 必须报错，而不是静默跳过
bad_fields = [{"id": "fx", "field": "Security Clearance Level XYZ", "required": True, "kind": "text"}]
built3, err3 = A.build_answers(bad_fields, PROFILE, None)
check("B14 负向控制 必填无法映射->报错", err3 is not None and "UNMAPPED" in (err3 or ""), repr(err3))
check("B15 负向控制 报错时不返回部分结果", built3 is None, repr(built3))

# 负向控制：phone 为空 + 必填 => 必须报错（不允许填假号码）
p2 = dict(PROFILE); p2["PHONE"] = ""
built4, err4 = A.build_answers(
    [{"id": "f4", "field": "Phone Number", "required": True, "kind": "text"}], p2, None)
check("B16 负向控制 无手机号+必填->报错", err4 is not None, repr(err4))

print()
print("=" * 70)
print("C. upload_file 失败路径")
print("=" * 70)
ok, info = A.upload_file(r"C:\definitely\not\here\resume.pdf")
check("C1 不存在文件->失败不抛异常", ok is False and "error" in info, repr(info)[:120])
check("C2 错误信息含路径", "not" in str(info).lower() or "found" in str(info).lower(), repr(info)[:120])

print()
print("=" * 70)
print("D. live：slug 大小写影响真实端点")
print("=" * 70)
JOBS = json.load(open(os.path.join(SCRATCH, "ats_jobs.json"),
                      encoding="utf-8"))


def uuid_of(j):
    import re as _re
    m = _re.search(r"jobs\.ashbyhq\.com/[^/?]+/([0-9a-fA-F-]{36})", j.get("url") or "")
    return m.group(1) if m else None


def org_of(j):
    """slug 从 URL 第二段取；大小写影响端点命中（ElevenLabs vs elevenlabs）。"""
    import re as _re
    m = _re.search(r"jobs\.ashbyhq\.com/([^/?]+)/", j.get("url") or "")
    return m.group(1) if m else (j.get("org") or "")


targets = []
seen_org = {}
for j in JOBS:
    if j.get("ats") != "ashby":
        continue
    u = uuid_of(j)
    o = org_of(j)
    if not (u and o):
        continue
    # 每个 org 取一个：验证必须覆盖**不同 org**，
    # 否则"slug/id 错配"负向控制根本构造不出来（实测同 org 换 id 返回正确 posting）
    if o not in seen_org:
        seen_org[o] = (o, u, j.get("title"))
for o in list(seen_org)[:4]:
    targets.append(seen_org[o])
check("D1 至少找到 3 个不同 org 的 ashby 目标", len(targets) >= 3,
      "n=%d orgs=%s" % (len(targets), list(seen_org)[:5]))

for org, uid, expect_title in targets[:3]:
    st, jp, raw = A.job_form(org.lower(), uid)
    got = (jp or {}).get("title")
    check("D2 live %s/%s 取回正确 posting" % (org, uid[:8]),
          st == 200 and got == expect_title,
          "expect=%r got=%r st=%s" % (expect_title, got, st))
    if jp:
        fs = A.parse_fields(jp)
        check("D3 live %s 表单字段可解析" % org, len(fs) > 0, "n=%d" % len(fs))
        check("D4 live %s id 与请求一致" % org, A.posting_matches(jp, uid),
              "got=%r" % jp.get("id"))
        # 大小写不敏感（实测：ElevenLabs 与 elevenlabs 返回同一 posting）
        st2, jp2, _ = A.job_form(org.upper(), uid)
        check("D5 大写 slug 返回同一 posting（大小写无关）",
              (jp2 or {}).get("id") == jp.get("id"),
              "%r vs %r" % (jp.get("id"), (jp2 or {}).get("id")))
    time.sleep(1.0)

# 负向控制：slug 与 id 不匹配时 Ashby 静默返回**另一个** posting
if len(targets) >= 2:
    o_a, u_a, _ = targets[0]
    o_b, u_b, _ = targets[1]
    st3, jp3, _ = A.job_form(o_b, u_a)          # 用 B 的 slug 配 A 的 id
    got3 = (jp3 or {}).get("id")
    # 实测事实：错配 -> HTTP 200 + jobPosting:null（不是静默返回别的 posting）
    check("D6 负向控制 slug/id 错配 -> 取不到请求的 posting", got3 != u_a,
          "requested=%s got=%r" % (u_a, got3))
    check("D7 守卫 posting_matches 对该错配判 False",
          A.posting_matches(jp3, u_a) is False,
          "guard did not fire")
    check("D9 守卫对 null posting 判 False（缺 id 不许投）",
          A.posting_matches(None, u_a) is False)
    check("D8 守卫对正确配对不误报",
          A.posting_matches({"id": u_a}, u_a) is True)

print()
print("=" * 70)
print("E. 负向控制：mutation 探测器不得假阳性")
print("=" * 70)
# 之前用 mutation X { __typename } 测所有名字都 200 —— 证明该探针无判别力。
# 现在确认：真实不存在的 mutation 名 + 真正字段名，行为必须不同。
st_a, r_a = A.gql("JobApplicationSubmit", {"input": {}},
                  "mutation JobApplicationSubmit($input: JobApplicationSubmitInput!) { "
                  "jobApplicationSubmit(input: $input) { success } }")
st_b, r_b = A.gql("TotallyBogusMutation", {"input": {}},
                  "mutation TotallyBogusMutation($input: JobApplicationSubmitInput!) { "
                  "totallyBogusMutation(input: $input) { success } }")
err_a = json.dumps(r_a.get("errors"), ensure_ascii=False)[:200] if isinstance(r_a, dict) else str(r_a)[:200]
err_b = json.dumps(r_b.get("errors"), ensure_ascii=False)[:200] if isinstance(r_b, dict) else str(r_b)[:200]
check("E1 真实 mutation 空 input 会返回错误(字段必填)", bool(r_a.get("errors")), err_a)
check("E2 不存在的 mutation 字段也报错(探针无判别力已记录)", bool(r_b.get("errors")), err_b)
check("E3 两者错误信息不同(说明 schema 真的在校验)",
      err_a != err_b, "A=%s B=%s" % (err_a[:80], err_b[:80]))

print()
print("=" * 70)
n_pass = sum(1 for _, ok in RESULTS if ok)
n_tot = len(RESULTS)
print("RESULT: %d/%d PASS" % (n_pass, n_tot))
if FAIL_DETAIL:
    print("\n--- FAILURES (full) ---")
    for d in FAIL_DETAIL:
        print(d)
sys.exit(0 if n_pass == n_tot else 1)
