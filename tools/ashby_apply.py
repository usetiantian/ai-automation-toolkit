# -*- coding: utf-8 -*-
"""
ashby_apply.py — Ashby 免账号 GraphQL 直投引擎。

为什么走 GraphQL 而不是浏览器点击：
1. 浏览器点击遇到 React 受控组件 / 文件上传 / reCAPTCHA 极易静默失败；
2. GraphQL 端点 `jobs.ashbyhq.com/api/non-user-graphql` 免账号、免邮箱验证码；
3. 可以无人值守批量跑，一次跑几百个岗位；
4. 服务端返回 success/errorMessage，是**硬回执**，不是"看起来提交了"。

真实契约（2026-11-13 从前端 query + "Did you mean" 泄漏反推并实测）：
  mutation JobApplicationSubmit($input: JobApplicationSubmitInput!) {
    jobApplicationSubmit(input: $input) { success errorMessage ... }
  }
  input 字段：jobPostingId, candidateFile, candidateFirstName, candidateLastName,
              candidateEmail, candidatePhoneNumber, candidateOrg, candidateUrl,
              candidateAdditionalInformation, candidateLocation, candidateWorkplaceType,
              candidateRequiresReview, jobCandidateAnswers
  文件：mutation FileUpload($file: FileUploadInput!) { fileUpload(file: $file) {
            success fileUrl file { id filename } } }

用法:
  python ashby_apply.py --plan plan.json          # 执行投递计划
  python ashby_apply.py --schema <jobPostingId>   # 只看某岗位的表单结构
"""
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.request

GQL_URL = "https://jobs.ashbyhq.com/api/non-user-graphql"
FILE_URL = "https://jobs.ashbyhq.com/api/non-user-graphql"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "outreach")


def gql(op, variables, query, retries=2):
    """POST GraphQL。返回 (status, parsed)。失败不吞异常信息。"""
    body = json.dumps({"operationName": op, "variables": variables, "query": query}).encode()
    hdr = {"Content-Type": "application/json", "User-Agent": UA,
           "Accept": "application/json", "Origin": "https://jobs.ashbyhq.com",
           "Referer": "https://jobs.ashbyhq.com/"}
    last = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(GQL_URL, data=body, headers=hdr)
            with urllib.request.urlopen(req, timeout=35, context=CTX) as r:
                return r.status, json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            try:
                return e.code, json.loads(raw)
            except Exception:
                return e.code, {"raw": raw[:600]}
        except Exception as e:
            last = e
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
    return 0, {"error": "%s: %s" % (type(last).__name__, last)}


# ---------- 岗位详情 ----------
JOB_Q = """query ApiJobPosting($organizationHostedJobsPageName: String!, $jobPostingId: String!) {
  jobPosting(organizationHostedJobsPageName: $organizationHostedJobsPageName, jobPostingId: $jobPostingId) {
    id title departmentName locationName workplaceType employmentType
    descriptionHtml compensationTierSummary
    applicationForm {
      id
      formControls { identifier title }
      errorMessages
      formErrors { message fieldEntryId }
      sections {
        title descriptionHtml isHidden
        fieldEntries {
          id field isRequired descriptionHtml isHidden
          fieldValue { __typename ... on JSONBox { value } ... on File { id filename }
                       ... on FileList { files { id filename } } }
        }
      }
      sourceFormDefinitionId
    }
    recaptchaAction
  }
}"""


def job_form(slug, jid):
    st, r = gql("ApiJobPosting",
                {"organizationHostedJobsPageName": slug, "jobPostingId": jid}, JOB_Q)
    jp = (r.get("data") or {}).get("jobPosting") if isinstance(r, dict) else None
    return st, jp, r


def posting_matches(jp, jid):
    """核对返回的 posting 就是请求的那个。

    实测事实（2026-11-13）：slug 与 id 错配时 Ashby 返回 HTTP 200 + `{"data":{"jobPosting":null}}`，
    不会静默返回另一个 posting。但 null / 缺 id 都必须判为"不匹配"——
    没有正向确认就不许投（宁可跳过，不可投错）。
    """
    got = (jp or {}).get("id")
    return bool(got) and str(got).lower() == str(jid).lower()


def parse_fields(jp):
    """把 applicationForm.sections[].fieldEntries[] 摊平成 [{id,field,required,kind}]。

    kind: text / textarea / file / filelist / select / checkbox / radio / hidden
    """
    out = []
    af = (jp or {}).get("applicationForm") or {}
    for sec in af.get("sections") or []:
        if sec.get("isHidden"):
            continue
        for fe in sec.get("fieldEntries") or []:
            if fe.get("isHidden"):
                continue
            fv = fe.get("fieldValue") or {}
            tn = fv.get("__typename") or ""
            kind = "text"
            if tn == "File":
                kind = "file"
            elif tn == "FileList":
                kind = "filelist"
            elif tn == "JSONBox":
                v = fv.get("value")
                if isinstance(v, dict):
                    vt = str(v.get("type") or "").lower()
                    if vt in ("select", "multi_select", "dropdown"):
                        kind = "select"
                    elif vt in ("checkbox", "radio", "toggle"):
                        kind = "checkbox"
                    elif vt == "textarea":
                        kind = "textarea"
                    elif vt in ("file", "resume"):
                        kind = "file"
                elif isinstance(v, str) and len(v) > 120:
                    kind = "textarea"
            out.append({
                "id": fe.get("id"),
                "field": fe.get("field"),
                "required": bool(fe.get("isRequired")),
                "kind": kind,
                "desc": (fe.get("descriptionHtml") or "")[:120],
            })
    return out


# ---------- 文件上传 ----------
FILE_Q = """mutation FileUpload($file: FileUploadInput!) {
  fileUpload(file: $file) { success fileUrl errorMessage file { id filename } }
}"""


def upload_file(path, filename=None, content_type=None):
    """上传简历，返回 (ok, fileobj)。fileobj = {"id":..., "filename":...}"""
    if not os.path.exists(path):
        return False, {"error": "file not found: %s" % path}
    fn = filename or os.path.basename(path)
    ct = content_type or ("application/pdf" if fn.lower().endswith(".pdf")
                           else "application/octet-stream")
    with open(path, "rb") as f:
        raw = f.read()
    # multipart/form-data，字段名必须是 "file"
    bnd = "----AshbyBoundary%s" % os.urandom(8).hex()
    parts = []
    parts.append(("--%s\r\n" % bnd).encode())
    parts.append(('Content-Disposition: form-data; name="file"; filename="%s"\r\n' % fn).encode())
    parts.append(("Content-Type: %s\r\n\r\n" % ct).encode())
    parts.append(raw)
    parts.append(("\r\n--%s--\r\n" % bnd).encode())
    payload = b"".join(parts)
    hdr = {"Content-Type": "multipart/form-data; boundary=%s" % bnd,
           "User-Agent": UA, "Accept": "application/json",
           "Origin": "https://jobs.ashbyhq.com",
           "Referer": "https://jobs.ashbyhq.com/"}
    try:
        req = urllib.request.Request(FILE_URL, data=payload, headers=hdr)
        with urllib.request.urlopen(req, timeout=60, context=CTX) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return False, {"error": "HTTP %s" % e.code,
                       "raw": e.read().decode("utf-8", "replace")[:400]}
    except Exception as e:
        return False, {"error": "%s: %s" % (type(e).__name__, e)}
    errs = d.get("errors")
    if errs:
        return False, {"error": json.dumps(errs)[:500]}
    fu = (d.get("data") or {}).get("fileUpload") or {}
    if not fu.get("success"):
        return False, {"error": fu.get("errorMessage") or json.dumps(d)[:400]}
    return True, {"id": (fu.get("file") or {}).get("id"), "filename": fn,
                  "fileUrl": fu.get("fileUrl")}


# ---------- 提交 ----------
SUBMIT_Q = """mutation JobApplicationSubmit($input: JobApplicationSubmitInput!) {
  jobApplicationSubmit(input: $input) {
    success
    errorMessage
    jobApplication { id }
  }
}"""


def submit(inp):
    st, r = gql("JobApplicationSubmit", {"input": inp}, SUBMIT_Q)
    res = (r.get("data") or {}).get("jobApplicationSubmit") if isinstance(r, dict) else None
    errs = r.get("errors") if isinstance(r, dict) else None
    if errs:
        return False, {"errors": errs}
    if not res:
        return False, {"raw": str(r)[:500]}
    if not res.get("success"):
        return False, {"errorMessage": res.get("errorMessage")}
    return True, res


# ---------- 从字段表构造 answers ----------
def build_answers(fields, profile, resume_file):
    """构造 jobCandidateAnswers + input。

    jobCandidateAnswers 形状：[{fieldEntryId, fieldValue:{value: ...}}]

    规则纪律（踩坑记录）：
    1. 匹配顺序有讲究 —— "Last Name" 里含 "name"，若先判 first/name/full
       就会把 Last Name 抢去填 FIRST。last/surname 必须先判。
    2. 没有兜底默认值。未识别的字段：必填 => 报错跳过整个岗位；
       非必填 => 跳过。绝不用 "Generic answer." 之类垃圾静默糊过去
       （那是把未映射伪装成已映射，最典型的假绿）。
    """
    answers = []
    used_files = []
    for f in fields:
        fid, fname, kind, req = f["id"], (f["field"] or ""), f["kind"], f["required"]
        low = fname.lower()
        val = None
        if kind in ("file", "filelist"):
            if resume_file:
                used_files.append(resume_file)
                answers.append({"fieldEntryId": fid,
                                "fieldValue": {"value": resume_file}})
            continue
        if kind == "textarea":
            val = profile.get("LONG")
        elif re.search(r"last|surname|family\s*name", low):
            val = profile.get("LAST")
        elif re.search(r"first|given|forename", low):
            val = profile.get("FIRST")
        elif re.search(r"full\s*name|your\s*name|candidate\s*name|^name$", low):
            f_, l_ = profile.get("FIRST"), profile.get("LAST")
            val = ("%s %s" % (f_, l_)).strip() if (f_ and l_) else (f_ or l_)
        elif re.search(r"e-?mail", low):
            val = profile.get("EMAIL")
        elif re.search(r"phone|tel|mobile|cell", low):
            val = profile.get("PHONE") or None
        elif re.search(r"current\s+(company|employer)|present\s+employer|^company$|^organization$|studio|brand", low):
            val = profile.get("ORG")
        elif re.search(r"web\s*site|website|^url$|portfolio|github|linkedin|^link$", low):
            val = profile.get("URL")
        elif re.search(r"location|city|country|based|timezone|country", low):
            val = profile.get("LOC")
        elif re.search(r"workplace|remote|hybrid|onsite|arrangement", low):
            val = profile.get("WORKPLACE")
        elif re.search(r"salary|comp|pay|rate|expect", low):
            val = profile.get("RATE")
        elif re.search(r"experience|years", low):
            val = profile.get("YEARS")
        elif re.search(r"cover|letter|note|additional|message|why|about|tell|summar", low):
            val = profile.get("LONG")
        # 无兜底：认不出来就当没这个字段
        if val is None:
            if req:
                return None, "REQUIRED_FIELD_UNMAPPED:%s(%s)" % (fname, kind)
            continue
        answers.append({"fieldEntryId": fid, "fieldValue": {"value": val}})
    return {"answers": answers, "files": used_files}, None


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--schema", help="只看某岗位表单结构 (jobPostingId)")
    ap.add_argument("--slug", default="trueshort")
    ap.add_argument("--plan", help="投递计划 json")
    ap.add_argument("--resume", default=os.path.join(OUT_DIR, "resume_en.pdf"))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if a.schema:
        st, jp, raw = job_form(a.slug, a.schema)
        print("HTTP", st)
        if not jp:
            print(json.dumps(raw, ensure_ascii=False)[:1500]); return 1
        print("title:", jp.get("title"), "| type:", jp.get("employmentType"),
              "| workplace:", jp.get("workplaceType"), "| loc:", jp.get("locationName"))
        fs = parse_fields(jp)
        print("recaptchaAction:", jp.get("recaptchaAction"))
        print("fields: %d" % len(fs))
        for f in fs:
            print("   %-8s req=%-5s %-34s %s" % (f["kind"], f["required"], f["field"], f["desc"][:60]))
        json.dump({"slug": a.slug, "job": jp, "fields": fs},
                  open(os.path.join(OUT_DIR, "ashby_schema_%s.json" % a.schema[:8]), "w",
                       encoding="utf-8"), ensure_ascii=False, indent=1)
        print("\nSAVED ashby_schema_%s.json" % a.schema[:8])
        return 0

    if not a.plan:
        print(__doc__)
        return 1
    plan = json.load(open(a.plan, encoding="utf-8"))
    profile = plan.get("profile") or {}
    targets = plan.get("targets") or []
    results = []
    for t in targets:
        slug, jid = t["slug"], t["jobPostingId"]
        rec = {"slug": slug, "jobPostingId": jid, "title": t.get("title"), "url": t.get("url")}
        st, jp, raw = job_form(slug, jid)
        if not jp:
            rec["status"] = "SCHEMA_FAIL"; rec["detail"] = str(raw)[:300]
            results.append(rec); print("[FAIL] %s schema" % jid); continue
        # 守卫：Ashby 对 slug+id 不匹配时**静默返回另一个 posting**。
        # 若不校验，就会拿 A 的表单答案投到 B 的 id 上 —— 静默错投。
        got_id = jp.get("id")
        if not posting_matches(jp, jid):
            rec["status"] = "SCHEMA_MISMATCH"
            rec["detail"] = "requested=%s got=%s title=%s" % (jid, got_id, jp.get("title"))
            results.append(rec); print("[MISMATCH] %s != %s (%s)" % (jid, got_id, jp.get("title", "")[:40])); continue
        if t.get("title") and jp.get("title") and t["title"] != jp["title"]:
            rec["title_drift"] = "%s -> %s" % (t["title"], jp["title"])
        fs = parse_fields(jp)
        rec["fields"] = len(fs)
        built, err = build_answers(fs, profile, None)
        if err:
            rec["status"] = "UNMAPPED"; rec["detail"] = err
            results.append(rec); print("[SKIP] %s %s" % (jid, err)); continue
        if a.dry_run:
            rec["status"] = "DRY_OK"; rec["answers_preview"] = built["answers"]
            results.append(rec); print("[DRY] %s %d fields OK" % (jid, len(built["answers"])))
            continue
        # 上传简历
        need_file = any(f["kind"] in ("file", "filelist") for f in fs)
        fobj = None
        if need_file:
            ok, fobj = upload_file(a.resume)
            if not ok:
                rec["status"] = "UPLOAD_FAIL"; rec["detail"] = json.dumps(fobj)[:300]
                results.append(rec); print("[FAIL] %s upload" % jid); continue
            rec["file"] = fobj
            built, err = build_answers(fs, profile, fobj)
            if err:
                rec["status"] = "UNMAPPED"; rec["detail"] = err
                results.append(rec); print("[SKIP] %s %s" % (jid, err)); continue
        inp = {
            "jobPostingId": jid,
            "candidateFirstName": profile.get("FIRST", ""),
            "candidateLastName": profile.get("LAST", ""),
            "candidateEmail": profile.get("EMAIL", ""),
            "candidatePhoneNumber": profile.get("PHONE", "") or "",
            "candidateOrg": profile.get("ORG", ""),
            "candidateUrl": profile.get("URL", ""),
            "candidateAdditionalInformation": profile.get("LONG", ""),
            "candidateLocation": profile.get("LOC", ""),
            "candidateWorkplaceType": profile.get("WORKPLACE", ""),
            "candidateRequiresReview": False,
            "jobCandidateAnswers": built["answers"],
        }
        if fobj:
            inp["candidateFile"] = fobj
        ok, res = submit(inp)
        rec["status"] = "SUBMITTED" if ok else "SUBMIT_FAIL"
        rec["receipt"] = res
        results.append(rec)
        print("[%s] %s %s" % ("OK " if ok else "FAIL", jid, t.get("title", "")[:44]))
        time.sleep(2.0)
    out = os.path.join(OUT_DIR, "ashby_apply_results.json")
    json.dump(results, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    ok_n = sum(1 for r in results if r["status"] == "SUBMITTED")
    print("\nSUBMITTED %d / %d -> %s" % (ok_n, len(results), out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
