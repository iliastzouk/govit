"""Proof of concept: find IT-related public-sector vacancies in the Cyprus Official Gazette.

Reads the latest issues of the Main Part, Section A (where vacancies are published),
downloads each PDF, splits it into numbered notices ("Αριθμός NNNN"), keeps the
vacancy notices and scores them against IT keywords. Writes everything to JSON.

No database, no AI, no email yet — this is only for measuring the keyword filter.
"""
from __future__ import annotations

import argparse
import json
import re
import tempfile
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote, urljoin

import certifi
import pymupdf as fitz
import requests
from bs4 import BeautifulSoup

from report import write_report

BASE = "https://www.mof.gov.cy/mof/gpo/gazette.nsf/"
SECTION_A_URL = BASE + "dmlgaz_view_sections_gr/dmlgaz_view_sections_gr?OpenDocument&sectionNumber=1&cp=22"
HERE = Path(__file__).parent
CACHE = HERE / "cache"
REQUEST_DELAY = 2.0  # seconds between requests to the gazette server

# ---------------------------------------------------------------- keywords
# Patterns run on accent-stripped, lowercased text (see normalize()).
# Final sigma is folded to σ, so patterns must never contain ς.
# The lookbehind on πληροφορικ excludes "γεωπληροφορικ".
STRONG = {
    "πληροφορική": r"(?<![a-zα-ω])πληροφορικ",
    "προγραμματιστής": r"προγραμματιστ",  # NOT προγραμματισμ (= planning)
    "επιστήμη υπολογιστών": r"επιστημ\w* (?:των )?(?:ηλεκτρονικων )?υπολογιστ",
    "μηχανική υπολογιστών": r"μηχανικ\w* (?:των )?(?:ηλεκτρονικων )?υπολογιστ",
    "τεχνολογίες πληροφοριών": r"τεχνολογι\w* (?:τησ )?πληροφορι",
    "κυβερνοασφάλεια": r"κυβερνοασφαλ",
    "ψηφιακή ασφάλεια": r"ψηφιακ\w* ασφαλει",
    "ασφάλεια πληροφοριών": r"ασφαλει\w* (?:των )?(?:πληροφοριων|συστηματων πληροφορ)",
    "βάσεις δεδομένων": r"βασε\w* δεδομενων",
    "αναλυτής συστημάτων": r"αναλυτ\w* (?:\w+ )?συστηματων",
    "computer science": r"computer (?:science|engineering)",
    "software": r"\bsoftware\b",
    "information technology": r"information (?:technology|systems)",
    "developer/programmer": r"\b(?:developer|programmer)s?\b",
    "cyber security": r"cyber ?security",
    "data science": r"data scien",
}
WEAK = {
    "λογισμικό": r"λογισμικ",
    "ψηφιακό": r"ψηφιακ",
    "ηλεκτρονικοί υπολογιστές": r"ηλεκτρονικ\w* υπολογιστ",
    "δίκτυα": r"δικτυ\w* (?:υπολογιστων|επικοινωνιων|δεδομενων)",
}
STRONG_RE = {k: re.compile(v) for k, v in STRONG.items()}
WEAK_RE = {k: re.compile(v) for k, v in WEAK.items()}

NOTICE_RE = re.compile(r"^\s*[AΑ]ριθμός\s+(\d{1,5})\.?\s*$")
# Decided on the notice heading + opening lines, so promotions/appointments that merely
# mention "κενή θέση" further down are not counted.
VACANCY_RE = re.compile(
    r"κεν(?:η|εσ|ησ|ων) θεσ(?:η|εισ|ησ|εων)|πληρωσ\w* (?:\w+ ){0,3}θεσ|προκηρυξ\w* (?:\w+ ){0,4}θεσ"
    r"|προσληψ\w* (?:\w+ ){0,2}εργοδοτουμεν|υποβολ\w* αιτησεων"
)
NOT_VACANCY_RE = re.compile(r"^(?:προαγωγ|διορισμ|αποσπασ|επικυρωσ|μεταθεσ|αφυπηρετ)|αποτελεσματ")
# Published results / merit lists of an earlier call, not a new call for applications.
OBJECTIONS_RE = re.compile(r"ενστασεισ μπορουν να υποβληθουν|υποβολη ενστασεων")
PERSON_LIST_RE = re.compile(r"ονοματεπωνυμο.{0,80}ταυτοτητασ")
# Latin letters that the PDFs sometimes use inside Greek words (e.g. "ΚΕΝH ΘΕΣH").
LATIN_TO_GREEK = str.maketrans("ABEHIKMNOPTXYZ", "ΑΒΕΗΙΚΜΝΟΡΤΧΥΖ")


MONTHS = ["ιανουαριου", "φεβρουαριου", "μαρτιου", "απριλιου", "μαιου", "ιουνιου",
          "ιουλιου", "αυγουστου", "σεπτεμβριου", "οκτωβριου", "νοεμβριου", "δεκεμβριου"]
_DATE = rf"(\d{{1,2}})(?:ησ?)?(?:\s*[/.]\s*(\d{{1,2}})\s*[/.]\s*|\s+({'|'.join(MONTHS)})\s*)(\d{{4}})"
# Deadlines are written as "μέχρι την Παρασκευή, 2 Οκτωβρίου 2026 και ώρα 14:00",
# "...είναι η 11η Σεπτεμβρίου 2026, ώρα 14:00" or "όχι αργότερα από τη Δευτέρα, 28 Σεπτεμβρίου 2026".
# Patterns are tried in order; the first one that finds a date wins.
DEADLINE_RES = [
    re.compile(rf"(?:μεχρι|εωσ|παρατεινεται)[^.]{{0,60}}?{_DATE}[^.]{{0,15}}?ωρα"),
    re.compile(rf"{_DATE}\s*,?\s*(?:και )?ωρα"),
    re.compile(rf"(?:αργοτερα απο|μεχρι|εωσ)[^.]{{0,40}}?{_DATE}"),
]
# Posts open only to serving public servants: promotion / inter-departmental promotion posts.
# "Πρώτου Διορισμού και Προαγωγής" is open to outsiders too, and does not match here because
# of the words between "θέση" and "προαγωγής".
PUBLIC_SERVANTS_ONLY_RE = re.compile(
    r"(?:μονο|αποκλειστικα) απο (?:δημοσιουσ|μονιμουσ) υπαλληλουσ"
    r"|θεσ\w* (?:ειναι )?\(?(?:διατμηματικησ )?προαγωγησ"
)


def normalize(text: str) -> str:
    """Accent-free, lowercase, whitespace-collapsed. Keeps the length of
    " ".join(text.split()) so match positions can be mapped back to the original."""
    text = " ".join(text.split())
    text = re.sub(r"\w*[Α-Ωα-ωΆ-ώ]\w*", lambda m: m.group().translate(LATIN_TO_GREEK), text)
    text = "".join(unicodedata.normalize("NFD", c)[0] for c in text)
    return text.lower().replace("ς", "σ")


def find_deadline(norm: str, published: date) -> date | None:
    for rx in DEADLINE_RES:
        found = []
        for m in rx.finditer(norm):
            day, month_num, month_name, year = m.groups()
            month = int(month_num) if month_num else MONTHS.index(month_name) + 1
            try:
                d = date(int(year), month, int(day))
            except ValueError:
                continue
            if d >= published:
                found.append(d)
        if found:
            return max(found)
    return None


# ---------------------------------------------------------------- http
def make_session() -> requests.Session:
    """The gazette server does not send its intermediate certificate, so we append it
    to certifi's roots instead of disabling verification."""
    bundle = Path(tempfile.gettempdir()) / "gazette_ca_bundle.pem"
    bundle.write_text(
        Path(certifi.where()).read_text() + "\n" + (HERE / "certs" / "sectigo-dv-r36.pem").read_text()
    )
    s = requests.Session()
    s.verify = str(bundle)
    s.headers["User-Agent"] = "CyprusGovITJobs-PoC/0.1 (personal job alert; weekly low-volume)"
    return s


def get(session: requests.Session, url: str, attempts: int = 3) -> requests.Response:
    """Large PDFs occasionally fail mid-transfer (a proxy dropping the connection),
    so each request gets a few tries with a growing pause."""
    for attempt in range(1, attempts + 1):
        time.sleep(REQUEST_DELAY * attempt)
        try:
            r = session.get(url, timeout=120)
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            if attempt == attempts:
                raise
            print(f"      retry {attempt}/{attempts - 1} after {type(e).__name__}")


# ---------------------------------------------------------------- discovery
@dataclass
class Issue:
    number: int
    date: str  # dd/mm/yyyy as shown on the site
    first_page: int
    doc_id: str
    doc_url: str
    pdf_url: str = ""


def list_issues(session) -> list[Issue]:
    soup = BeautifulSoup(get(session, SECTION_A_URL).content, "html.parser")
    # Each row has three links (number, date, pages) pointing to the same document.
    cells: dict[str, list[str]] = {}
    for a in soup.find_all("a", href=re.compile(r"/All/[0-9A-F]{32}\?OpenDocument", re.I)):
        cells.setdefault(a["href"], []).append(a.get_text(strip=True))
    issues = []
    for href, (number, date, pages, *_) in ((h, c) for h, c in cells.items() if len(c) >= 3):
        if not number.isdigit():
            continue
        doc_id = re.search(r"/All/([0-9A-F]{32})", href, re.I).group(1)
        issues.append(Issue(int(number), date, int(pages.split("-")[0]), doc_id, urljoin(BASE, href)))
    return sorted(issues, key=lambda i: i.number, reverse=True)


def find_pdf_url(session, issue: Issue) -> str:
    soup = BeautifulSoup(get(session, issue.doc_url).content, "html.parser")
    pdfs = [a["href"] for a in soup.find_all("a", href=True) if "$file" in a["href"] and a["href"].lower().endswith(".pdf")]
    if not pdfs:
        raise RuntimeError(f"No PDF link on {issue.doc_url}")
    return urljoin(issue.doc_url, quote(pdfs[0], safe="/$.-_"))


def download_pdf(session, issue: Issue) -> Path:
    CACHE.mkdir(exist_ok=True)
    path = CACHE / f"{issue.number}.pdf"
    if not path.exists():
        path.write_bytes(get(session, issue.pdf_url).content)
    return path


# ---------------------------------------------------------------- parsing
@dataclass
class Notice:
    issue_number: int
    issue_date: str
    notice_number: int
    gazette_page: int
    pdf_page: int
    organization: str = ""
    title: str = ""
    is_vacancy: bool = False
    score: int = 0
    category: str = ""  # it_role | it_mentioned | not_it
    matched: list[str] = field(default_factory=list)
    snippets: list[str] = field(default_factory=list)
    deadline: str | None = None  # ISO date
    public_servants_only: bool = False
    text: str = ""


def split_notices(pdf: Path, issue: Issue) -> tuple[list[Notice], int]:
    doc = fitz.open(pdf)
    notices: list[Notice] = []
    chars = 0
    lines_buf: list[str] = []
    for pno, page in enumerate(doc):
        page_text = page.get_text("text", sort=True)
        chars += len(page_text.strip())
        for line in page_text.splitlines():
            m = NOTICE_RE.match(line)
            if m:
                if notices:
                    notices[-1].text = "\n".join(lines_buf)
                lines_buf = []
                notices.append(Notice(issue.number, issue.date, int(m.group(1)),
                                      issue.first_page + pno, pno + 1))
            elif notices:
                lines_buf.append(line)
    if notices:
        notices[-1].text = "\n".join(lines_buf)
    return notices, chars


def is_caps_line(line: str) -> bool:
    letters = [c for c in line if c.isalpha()]
    return len(letters) >= 4 and all(c.isupper() for c in letters)


def analyse(n: Notice) -> None:
    raw = re.sub(r"-\s*\n\s*", "", n.text)  # re-join hyphenated words
    lines = [l.strip() for l in raw.splitlines() if l.strip()]
    heading = []
    for l in lines[:8]:
        if is_caps_line(l):
            heading.append(l)
        elif heading:
            break
    title_lines = [l for l in heading if VACANCY_RE.search(normalize(l)) or normalize(l).startswith(("θεσ", "προκηρυξ"))]
    n.title = " ".join(title_lines) or " ".join(heading[-1:])
    n.organization = " ".join(l for l in heading if l not in title_lines)

    flat = " ".join(raw.split())
    norm = normalize(flat)
    published = datetime.strptime(n.issue_date, "%d/%m/%Y").date()
    deadline = find_deadline(norm, published)
    n.deadline = deadline.isoformat() if deadline else None
    n.public_servants_only = bool(PUBLIC_SERVANTS_ONLY_RE.search(norm))
    head = normalize(" ".join(heading))
    n.is_vacancy = (
        bool(VACANCY_RE.search(normalize(" ".join(lines[:12]))))
        and not NOT_VACANCY_RE.search(head)
        and not OBJECTIONS_RE.search(norm)  # its date is an objections deadline
        and not (deadline is None and PERSON_LIST_RE.search(norm))
    )
    norm_title = normalize(n.title)
    title_hit = False
    for name, rx in STRONG_RE.items():
        m = rx.search(norm)
        if m:
            n.score += 3
            n.matched.append(name)
            n.snippets.append(_snippet(flat, m))
            title_hit |= bool(rx.search(norm_title))
    for name, rx in WEAK_RE.items():
        m = rx.search(norm)
        if m:
            n.score += 1
            n.matched.append(name)
            if len(n.snippets) < 4:
                n.snippets.append(_snippet(flat, m))
    n.snippets = n.snippets[:4]
    if title_hit:
        n.category = "it_role"
    elif n.score >= 3:
        n.category = "it_mentioned"  # e.g. engineer post that also accepts a CS degree
    else:
        n.category = "not_it"


def _snippet(flat: str, m: re.Match, width: int = 110) -> str:
    return "…" + flat[max(0, m.start() - width): m.end() + width] + "…"


# ---------------------------------------------------------------- main
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=20, help="how many latest issues to scan")
    ap.add_argument("--issue", type=int, help="scan only this issue number")
    ap.add_argument("--out", default=str(HERE / "results.json"))
    ap.add_argument("--keep-text", action="store_true", help="include full notice text in JSON")
    ap.add_argument("--report", default=str(HERE / "report.html"))
    ap.add_argument("--today", type=date.fromisoformat, default=date.today(), help="YYYY-MM-DD, for testing")
    args = ap.parse_args()

    session = make_session()
    issues = list_issues(session)
    print(f"Found {len(issues)} issues in Section A listing (latest {issues[0].number} on {issues[0].date})")
    issues = [i for i in issues if i.number == args.issue] if args.issue else issues[: args.limit]

    report = {"issues": [], "vacancies": []}
    for issue in issues:
        entry = {**asdict(issue), "status": "ok"}
        try:
            issue.pdf_url = entry["pdf_url"] = find_pdf_url(session, issue)
            pdf = download_pdf(session, issue)
            notices, chars = split_notices(pdf, issue)
            if chars < 500:
                entry["status"] = "needs_review_no_text"
            for n in notices:
                analyse(n)
            vac = [n for n in notices if n.is_vacancy]
            cands = [n for n in vac if n.category != "not_it"]
            entry.update(notices=len(notices), vacancy_notices=len(vac), it_candidates=len(cands), text_chars=chars)
            for n in vac:
                d = asdict(n)
                if not args.keep_text:
                    d.pop("text")
                d["pdf_url"] = issue.pdf_url
                report["vacancies"].append(d)
            print(f"  #{issue.number} {issue.date}: {len(notices):3} notices, {len(vac):2} vacancy, {len(cands)} IT candidates")
            for n in cands:
                print(f"      [{n.category:12}] Αρ.{n.notice_number} σ.{n.gazette_page} score={n.score:2} "
                      f"{n.organization[:40]} | {n.title[:70]}  <{', '.join(n.matched)}>")
        except Exception as e:  # keep going; one bad issue must not stop the run
            entry["status"] = f"failed: {e}"
            print(f"  #{issue.number}: FAILED {e}")
        report["issues"].append(entry)

    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    total = [v for v in report["vacancies"] if v["category"] != "not_it"]
    print(f"\n{len(report['vacancies'])} vacancy notices, {len(total)} IT candidates -> {args.out}")
    shown = write_report(report, Path(args.report), args.today)
    print(f"{shown} open IT candidates -> {args.report}")


if __name__ == "__main__":
    main()
