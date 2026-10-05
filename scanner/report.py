"""Human-readable HTML report of open IT vacancies."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from html import escape
from pathlib import Path

# Notices without a detectable deadline are shown only if published this recently.
UNKNOWN_DEADLINE_MAX_AGE = timedelta(days=45)

SECTIONS = [
    ("it_role", "Θέσεις Πληροφορικής",
     "Η Πληροφορική ή η Ψηφιακή Ασφάλεια εμφανίζεται στον τίτλο της θέσης."),
    ("it_mentioned", "Πιθανώς σχετικές",
     "Η Πληροφορική αναφέρεται μόνο στο κείμενο — π.χ. γίνεται δεκτό πτυχίο Πληροφορικής, "
     "ή ζητούνται απλώς γνώσεις υπολογιστών. Χρειάζεται έλεγχος."),
]

CSS = """
:root{--bg:#f6f7f9;--card:#fff;--text:#1b1f24;--muted:#5b6470;--line:#e2e5ea;--accent:#0b5cad;
--urgent-bg:#fdecea;--urgent:#b3261e;--ok-bg:#e8f3ec;--ok:#1e6b3a;--warn-bg:#fff4dc;--warn:#8a5a00;--tag-bg:#eef1f5}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#111418;--card:#1a1e24;--text:#e6e9ee;
--muted:#9aa3ae;--line:#2b313a;--accent:#6fb1ff;--urgent-bg:#3a1d1b;--urgent:#ff9b92;--ok-bg:#16301f;--ok:#8fd6a6;
--warn-bg:#352a12;--warn:#f0c46a;--tag-bg:#252b33}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:860px;margin:0 auto;padding:24px 16px 48px}
h1{font-size:24px;margin:0 0 4px}
h2{font-size:18px;margin:32px 0 2px}
.sub,.hint{color:var(--muted);margin:0 0 12px}
.hint{font-size:13px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:10px 0}
.top{display:flex;gap:12px;justify-content:space-between;align-items:flex-start;flex-wrap:wrap}
.title{font-weight:600;font-size:15px;margin:0}
.org{color:var(--muted);font-size:13px;margin:2px 0 0}
.badge{white-space:nowrap;border-radius:999px;padding:3px 10px;font-size:13px;font-weight:600}
.badge.ok{background:var(--ok-bg);color:var(--ok)}
.badge.urgent{background:var(--urgent-bg);color:var(--urgent)}
.badge.unknown{background:var(--warn-bg);color:var(--warn)}
.meta{display:flex;flex-wrap:wrap;gap:6px 14px;margin:10px 0 0;font-size:13px;color:var(--muted)}
.tag{background:var(--tag-bg);border-radius:6px;padding:1px 7px;font-size:12px;color:var(--text)}
a{color:var(--accent)}
details{margin-top:8px;font-size:13px}
summary{cursor:pointer;color:var(--muted)}
blockquote{margin:6px 0;padding:6px 10px;border-left:3px solid var(--line);color:var(--muted)}
.ai{margin-top:10px;padding:10px 12px;border:1px solid var(--line);border-radius:8px;background:var(--tag-bg)}
.ai p{margin:4px 0;font-size:14px}
.ai-head{font-weight:600;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.ai ul{margin:6px 0;padding-left:20px;font-size:13px;color:var(--muted)}
.notice{margin-top:8px;max-height:55vh;overflow:auto;padding:10px;background:var(--tag-bg);border-radius:8px;
font-size:13px;line-height:1.65;text-align:justify}
.empty{color:var(--muted);font-style:italic}
footer{margin-top:40px;color:var(--muted);font-size:12px}
"""


def _parse(d: str) -> date:
    return datetime.strptime(d, "%d/%m/%Y").date()


def _badge(deadline: date | None, today: date) -> str:
    if deadline is None:
        return '<span class="badge unknown">Προθεσμία: δες το ΦΕΚ</span>'
    days = (deadline - today).days
    when = "σήμερα" if days == 0 else "αύριο" if days == 1 else f"σε {days} μέρες"
    cls = "urgent" if days <= 7 else "ok"
    return f'<span class="badge {cls}">Λήγει {when} · {deadline:%d/%m/%Y}</span>'


FIT = {"good": ("ok", "Ταιριάζει στο προφίλ"), "partial": ("unknown", "Ταιριάζει εν μέρει"),
       "poor": ("", "Δεν ταιριάζει στο προφίλ")}
VERDICT = {"direct_it": "Θέση Πληροφορικής", "it_degree_accepted": "Δεκτό πτυχίο Πληροφορικής",
           "it_skills_only": "Απλώς γνώσεις υπολογιστών", "not_it": "Άσχετη με Πληροφορική"}


def _ai_block(ai: dict) -> str:
    """What the model made of the notice. Shown next to the original text, never instead of it."""
    cls, label = FIT.get(ai.get("fit_for_profile", ""), ("", ""))
    quals = "".join(f"<li>{escape(q)}</li>" for q in ai.get("qualifications", [])[:10])
    return f"""
  <div class="ai">
    <p class="ai-head">{escape(VERDICT.get(ai.get("verdict", ""), ""))}
      {f'<span class="badge {cls}">{label}</span>' if label else ""}</p>
    <p>{escape(ai.get("summary", ""))}</p>
    {f'<p class="org">{escape(ai["employment_type"])}</p>' if ai.get("employment_type") else ""}
    {f'<details><summary>Απαιτούμενα προσόντα</summary><ul>{quals}</ul></details>' if quals else ""}
    {f'<p class="org">Καταλληλότητα: {escape(ai["fit_reason"])}</p>' if ai.get("fit_reason") else ""}
  </div>"""


def _card(v: dict, today: date) -> str:
    deadline = date.fromisoformat(v["deadline"]) if v["deadline"] else None
    tags = []
    if v["title"].startswith("ΠΑΡΑΤΑΣΗ"):
        tags.append("Παράταση προθεσμίας")
    if v["public_servants_only"]:
        tags.append("Μόνο για δημόσιους υπαλλήλους")
    tags += v["matched"][:4]
    snippets = "".join(f"<blockquote>{escape(s)}</blockquote>" for s in v["snippets"][:3])
    # Phones open PDFs in an external viewer that ignores #page, so the full notice is
    # inlined here and the PDF is only a fallback.
    full_text = (f"<details><summary>Πλήρες κείμενο ανακοίνωσης</summary>"
                 f"<div class='notice'>{escape(v['text'])}</div></details>") if v.get("text") else ""
    return f"""
<article class="card">
  <div class="top">
    <div>
      <p class="title">{escape(v["title"] or "(χωρίς τίτλο)")}</p>
      <p class="org">{escape(v["organization"])}</p>
    </div>
    {_badge(deadline, today)}
  </div>
  <div class="meta">
    <span>ΦΕΚ {v["issue_number"]} · {v["issue_date"]} · Αρ. {v["notice_number"]} · σελ. {v["gazette_page"]}</span>
    <a href="{escape(v["pdf_url"])}#page={v["pdf_page"]}" target="_blank" rel="noopener">Άνοιγμα PDF (σελ. {v["pdf_page"]}) →</a>
  </div>
  <div class="meta">{"".join(f'<span class="tag">{escape(t)}</span>' for t in tags)}</div>
  {_ai_block(v["ai"]) if v.get("ai") else ""}
  {full_text}
  <details><summary>Γιατί εντοπίστηκε</summary>{snippets}</details>
</article>"""


def select_open(report: dict, today: date) -> tuple[dict[str, list[dict]], list[dict], int]:
    """Split the IT candidates into (still open, by category), (open but internal-only)
    and a count of the ones whose deadline has passed."""
    open_items: dict[str, list[dict]] = {key: [] for key, *_ in SECTIONS}
    internal: list[dict] = []
    hidden = 0
    for v in report["vacancies"]:
        if v["category"] not in open_items:
            continue
        if v["deadline"]:
            keep = date.fromisoformat(v["deadline"]) >= today
        else:
            keep = today - _parse(v["issue_date"]) <= UNKNOWN_DEADLINE_MAX_AGE
        if not keep:
            hidden += 1
        elif v["public_servants_only"]:
            internal.append(v)
        else:
            open_items[v["category"]].append(v)
    return open_items, internal, hidden


def write_report(report: dict, out: Path, today: date) -> int:
    open_items, internal, hidden = select_open(report, today)

    body = []
    for key, heading, hint in SECTIONS:
        items = sorted(open_items[key], key=lambda v: (v["deadline"] is None, v["deadline"] or "", -v["issue_number"]))
        body.append(f"<h2>{heading} ({len(items)})</h2><p class='hint'>{hint}</p>")
        body.append("".join(_card(v, today) for v in items) or "<p class='empty'>Καμία ανοιχτή θέση.</p>")

    if internal:
        internal.sort(key=lambda v: (v["deadline"] is None, v["deadline"] or ""))
        body.append(
            f"<h2>Μόνο για δημόσιους υπαλλήλους ({len(internal)})</h2>"
            "<p class='hint'>Θέσεις Προαγωγής ή Διατμηματικής Προαγωγής, όπου γίνονται δεκτές αιτήσεις "
            "μόνο από υπηρετούντες δημόσιους υπαλλήλους.</p>"
            "<details><summary>Εμφάνιση</summary>"
            + "".join(_card(v, today) for v in internal)
            + "</details>"
        )

    issues = report["issues"]
    numbers = [i["number"] for i in issues]
    failed = [i for i in issues if i["status"] != "ok"]
    shown = sum(len(v) for v in open_items.values())
    html = f"""<!doctype html>
<html lang="el"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Θέσεις Πληροφορικής Δημοσίου</title>
<style>{CSS}</style></head>
<body><main>
<h1>Θέσεις Πληροφορικής στο Δημόσιο</h1>
<p class="sub">{shown} ανοιχτές θέσεις · ενημέρωση {today:%d/%m/%Y} ·
ελέγχθηκαν {len(issues)} τεύχη ({min(numbers, default="-")}–{max(numbers, default="-")}) ·
{hidden} με προθεσμία που έληξε δεν εμφανίζονται{f" · {len(internal)} μόνο για δημόσιους υπαλλήλους" if internal else ""}</p>
{"".join(body)}
{"<p class='hint'>Τεύχη με πρόβλημα: " + escape(", ".join(f"{i['number']} ({i['status']})" for i in failed)) + "</p>" if failed else ""}
<footer>Πηγή: Επίσημη Εφημερίδα της Δημοκρατίας, Κύριο Μέρος, Τμήμα Α. Οι προθεσμίες εντοπίζονται αυτόματα —
επιβεβαίωσε πάντα στο πρωτότυπο ΦΕΚ πριν κάνεις αίτηση.</footer>
</main></body></html>"""
    out.write_text(html, encoding="utf-8")
    return shown


def main() -> None:
    """Rebuild report.html from results.json — used after the AI step adds its fields."""
    import json

    results = json.loads((Path(__file__).parent / "results.json").read_text(encoding="utf-8"))
    out = Path(__file__).parent / "report.html"
    print(f"{write_report(results, out, date.today())} open IT candidates -> {out}")


if __name__ == "__main__":
    main()
