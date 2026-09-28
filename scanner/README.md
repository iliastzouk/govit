# Cyprus Gazette IT jobs — proof of concept

Scans the latest issues of the Official Gazette (Main Part, Section A), splits each PDF
into numbered notices and flags vacancy notices that relate to IT.

```bash
pip install -r requirements.txt
python poc.py                 # latest 20 issues -> results.json
python poc.py --issue 5887    # one issue
python poc.py --keep-text     # include full notice text in the JSON
```

Outputs:
- `report.html` — readable list of IT vacancies that are still open (open it in a browser).
- `results.json` — all vacancy notices with category, deadline and snippets.

PDFs are cached in `cache/` (one file per issue number).

## Deadlines

The deadline is detected from phrases like "μέχρι την Παρασκευή, 2 Οκτωβρίου 2026 και ώρα 14:00".
The report hides notices whose deadline has passed. Notices with no detectable deadline are
shown for 45 days after publication, marked "δες το ΦΕΚ". Results lists, exam results and
merit lists are not counted as vacancies.

## Automation

`.github/workflows/scan.yml` runs the scan on GitHub, every Friday evening and again on
Monday morning (issues are normally published on Friday, but mid-week issues happen).
It commits the refreshed `report.html` / `results.json` and opens a GitHub issue listing
whatever is new, which arrives as a notification on the phone.

`notify.py` keeps `notified.json` so each vacancy is announced once. It also sends an email
through Resend when the repository secrets `RESEND_API_KEY` and `EMAIL_TO` are set
(optional `EMAIL_FROM`, default Resend's sandbox sender); without them it just prints a note.

## Posts closed to outsiders

Posts marked "(Η θέση είναι Διατμηματικής Προαγωγής)" or "Προαγωγής", and posts whose text
says applications are accepted only from serving public servants, are moved to a separate
collapsed section of the report. "Πρώτου Διορισμού και Προαγωγής" is open to outsiders and
stays in the main list.

## Categories

- `it_role` — an IT keyword appears in the post title (e.g. Λειτουργός Πληροφορικής).
- `it_mentioned` — an IT keyword appears only in the body, typically because an IT degree
  is accepted for a non-IT post. The AI step will separate the relevant ones from noise.
- `not_it` — everything else.

## Notes

- `certs/sectigo-dv-r36.pem`: www.mof.gov.cy does not send its intermediate certificate,
  so it is appended to certifi's bundle. TLS verification stays on. The intermediate is
  valid until 2036.
- The PDFs are generated from Word, so text extraction works and no OCR is needed. An issue
  with almost no text is marked `needs_review_no_text`.
- Final sigma is folded to `σ` before matching, so keyword patterns must never contain `ς`.
