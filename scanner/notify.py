"""Decide what is worth notifying about, and optionally send the email.

A vacancy is notified once, the first time it shows up as open and open to outsiders.
`notified.json` is committed by the workflow, so the history survives between runs.
"""
from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

import requests

from report import select_open

HERE = Path(__file__).parent
NOTIFIED = HERE / "notified.json"
REPO_URL = "https://github.com/iliastzouk/govit"
LABELS = {"it_role": "Θέση Πληροφορικής", "it_mentioned": "Πιθανώς σχετική"}


def key(v: dict) -> str:
    return f"{v['issue_number']}-{v['notice_number']}"


def load_notified() -> set[str]:
    if NOTIFIED.exists():
        return set(json.loads(NOTIFIED.read_text(encoding="utf-8")))
    return set()


def describe(v: dict) -> str:
    title = " ".join(v["title"].split()) or "(χωρίς τίτλο)"
    org = " ".join(v["organization"].split())
    deadline = f"**{date.fromisoformat(v['deadline']):%d/%m/%Y}**" if v["deadline"] else "δες το ΦΕΚ"
    out = (
        f"### {title}\n\n"
        f"- **Φορέας:** {org}\n"
        f"- **Προθεσμία:** {deadline}\n"
        f"- **Κατηγορία:** {LABELS[v['category']]}\n"
        f"- **Πηγή:** ΦΕΚ {v['issue_number']} ({v['issue_date']}), ανακοίνωση {v['notice_number']}, "
        f"σελίδα {v['gazette_page']} — [άνοιγμα PDF]({v['pdf_url']}#page={v['pdf_page']})\n"
    )
    if ai := v.get("ai"):
        quals = "".join(f"  - {q}\n" for q in ai.get("qualifications", [])[:8])
        out += (f"\n{ai.get('summary', '')}\n\n"
                f"- **Τύπος:** {ai.get('employment_type', '-')}\n"
                f"- **Καταλληλότητα:** {ai.get('fit_for_profile', '-')} — {ai.get('fit_reason', '')}\n"
                + (f"- **Προσόντα:**\n{quals}" if quals else ""))
    return out


def send_email(subject: str, markdown: str) -> str:
    """Sends through Resend when both secrets are set; otherwise does nothing."""
    api_key, to = os.environ.get("RESEND_API_KEY"), os.environ.get("EMAIL_TO")
    if not api_key or not to:
        return "email skipped (RESEND_API_KEY / EMAIL_TO not set)"
    html = markdown.replace("\n", "<br>")
    r = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"from": os.environ.get("EMAIL_FROM", "onboarding@resend.dev"),
              "to": [to], "subject": subject, "html": html},
        timeout=30,
    )
    return f"email sent ({r.status_code})" if r.ok else f"email failed: {r.status_code} {r.text[:200]}"


def main() -> None:
    results = json.loads((HERE / "results.json").read_text(encoding="utf-8"))
    today = date.today()
    open_items, internal, _ = select_open(results, today)

    notified = load_notified()
    fresh = [v for items in open_items.values() for v in items if key(v) not in notified]
    fresh.sort(key=lambda v: (v["category"] != "it_role", v["deadline"] or "9999"))
    still_open = sum(len(v) for v in open_items.values())

    if fresh:
        roles = sum(1 for v in fresh if v["category"] == "it_role")
        subject = (f"{len(fresh)} νέες θέσεις στην Επίσημη Εφημερίδα"
                   if len(fresh) > 1 else "Νέα θέση στην Επίσημη Εφημερίδα")
        body = (f"Βρέθηκαν **{len(fresh)}** νέες θέσεις ({roles} καθαρά Πληροφορικής).\n\n"
                + "\n".join(describe(v) for v in fresh)
                + f"\n---\n\nΣυνολικά ανοιχτές: {still_open}. "
                  f"[Πλήρης αναφορά]({REPO_URL}/blob/main/scanner/report.html)\n")
        (HERE / "notify.md").write_text(body, encoding="utf-8")
        print(send_email(subject, body))
        NOTIFIED.write_text(json.dumps(sorted(notified | {key(v) for v in fresh}), indent=1), encoding="utf-8")
    else:
        subject = ""
        print("no new vacancies")

    if out := os.environ.get("GITHUB_OUTPUT"):
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"new_count={len(fresh)}\nsubject={subject}\n")
    print(f"{len(fresh)} new, {still_open} open, {len(internal)} internal-only")


if __name__ == "__main__":
    main()
