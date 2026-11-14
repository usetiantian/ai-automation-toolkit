# ai-automation-toolkit

Keyless automation for technical hiring pipelines and open-source bounty hunting.
Everything here runs against **public, keyless APIs** — no account, no API token,
no captcha, no email verification code.

> Every claim in this README is backed by a runnable check in `tests/`.
> The verification suite is the product: a tool that cannot prove itself
> is a tool that will silently send your application to the wrong job posting.

---

## What is in here

| Tool | What it does | Keyless? |
|---|---|---|
| `tools/ats_harvest.py` | Harvests job postings from 8 ATS platforms (Ashby, Lever, Greenhouse, Workable, SmartRecruiters, Recruitee, Personio, BambooHR), auto-detects which ATS a company uses, scores by technical keywords | yes |
| `tools/ashby_apply.py` | Submits a job application to Ashby **without an account**, via the public GraphQL endpoint. Handles file upload, form-field mapping, and verifies the posting identity before submitting | yes |
| `tools/bounty_harvest.py` | Finds open PR bounties on GitHub, extracts the reward from the label, and **rejects bounty-farm/spam repos** | yes |
| `tools/browser_form.py` | Chrome DevTools Protocol driver: dynamic port discovery, DOM reads, form filling, tab management | — |
| `tools/form_submit.py` | Field classifier (email / url / phone / textarea / select / file), value extraction and submission | — |
| `tools/make_resume.py` | Generates an ATS-friendly resume (Markdown + HTML + PDF) | — |

---

## The interesting problem: keyless Ashby applications

Ashby renders its application form in React — there is no `<form>` element to
submit. The naive approach is to drive the browser. That works, but it is slow,
fragile, and hard to run unattended.

Instead, this toolkit reconstructs the form from the public GraphQL API and
submits it over plain HTTP.

**The contract** (verified against live endpoints, not documentation):

```
POST https://jobs.ashbyhq.com/api/non-user-graphql

mutation jobApplicationSubmit($input: JobApplicationSubmitInput!) {
  jobApplicationSubmit(input: $input) {
    success
    errorMessage
  }
}
```

```jsonc
{
  "jobPostingId": "<uuid>",
  "candidateFile": { "fileUrl": "...", "filename": "resume.pdf" },
  "candidateFirstName": "...",
  "candidateLastName": "...",
  "candidateEmail": "...",
  "candidatePhoneNumber": "...",
  "candidateOrg": "...",
  "candidateUrl": "...",
  "candidateAdditionalInformation": "...",
  "candidateLocation": "...",
  "candidateWorkplaceType": "...",
  "candidateRequiresReview": true,
  "jobCandidateAnswers": [
    { "fieldEntryId": "<field id, NOT the display label>", "value": "..." }
  ]
}
```

Two traps that this toolkit explicitly handles:

1. **`fieldEntryId` is not the visible label.** The form exposes both
   `fieldEntries[].id` (the id) and `fieldEntries[].field` (the label shown to
   a human). Answers must be keyed by the **id**.
2. **A mismatched slug/id pair must never be submitted.** If the board slug and
   the job id do not belong together, the server may answer with a posting you
   did not intend. `ashby_apply.py` compares the returned `jobPosting.id`
   against the requested id and refuses to submit unless they match
   (case-insensitively).

Unknown form fields are **not** filled with a generic placeholder string.
If a required field cannot be mapped, the whole posting is skipped and reported.

---

## Verification

```bash
python tests/test_ashby_apply.py    # direct
python -m pytest -q                 # same suite, pytest entry point
```

```
RESULT: 45/45 PASS
```

The suite checks the real GraphQL schema against live endpoints, the field
mapping rules, the file-upload failure path, id/org parsing, and the
posting-mismatch guard — including negative controls that must fail if the
guard is removed.

Live fixtures are committed under `tests/fixtures/` so a fresh clone runs
without setup. If they are missing, the suite regenerates them from
`tools/` and says exactly which command failed — it never aborts with a bare
`FileNotFoundError`.

---

## Design notes

* **No silent degradation.** A missing dependency or an unverified endpoint
  raises. It never silently falls back to a weaker path.
* **Stale artefacts are deleted before they are regenerated.** Checking
  "does the output file exist" after a step that may have silently failed is a
  false green; the file is removed first so existence means something.
* **Browser drivers are stubs.** `msedge.exe` returns exit code 0 immediately
  while the real browser works in the background, so output has to be polled
  for rather than checked once.
* **Ports are discovered, not assumed.** The CDP port is read from
  `DevToolsActivePort` in the browser profile, because Chromium may pick a
  different port on every launch.
* **Bounty farms are filtered out.** A label scan surfaces repositories that
  exist purely to trap automated contributors — they mass-create issues with
  huge fake rewards and labels like *"AI only allowed - no humans"*. The
  harvester rejects repos by issue concentration, by those labels, and by
  account age.

---

## Install

```bash
pip install websocket-client
```

Everything else is standard library.

---

## License

MIT
