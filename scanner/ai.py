"""Ask OpenAI to read each candidate notice and pull out the structured details.

Only notices that the keyword filter already flagged are sent, and every answer is cached
in ai_cache.json by issue-notice, so a notice is paid for once. The model's verdict never
removes anything from the report: it adds a summary, the qualifications and a judgement of
whether the post really is an IT post. The original text stays alongside it.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import requests

HERE = Path(__file__).parent
CACHE = HERE / "ai_cache.json"
MODEL = os.environ.get("OPENAI_MODEL", "gpt-5-mini")
# The profile the model judges the post against.
PROFILE = os.environ.get(
    "CANDIDATE_PROFILE",
    "Προγραμματιστής με πτυχίο Πληροφορικής και εμπειρία σε C#/.NET, React, SQL Server.",
)

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["is_it_post", "verdict", "job_title", "organization", "employment_type",
                 "qualifications", "deadline", "summary", "fit_for_profile", "fit_reason"],
    "properties": {
        "is_it_post": {"type": "boolean",
                       "description": "Η ίδια η θέση αφορά Πληροφορική/υπολογιστές."},
        "verdict": {"type": "string", "enum": ["direct_it", "it_degree_accepted", "it_skills_only", "not_it"],
                    "description": "direct_it: θέση Πληροφορικής. it_degree_accepted: άλλη ειδικότητα "
                                   "που δέχεται και πτυχίο Πληροφορικής. it_skills_only: ζητά απλώς "
                                   "γνώσεις υπολογιστών. not_it: άσχετη."},
        "job_title": {"type": "string"},
        "organization": {"type": "string"},
        "employment_type": {"type": "string",
                            "description": "π.χ. μόνιμη θέση, εργοδοτούμενος ορισμένου χρόνου, ωρομίσθιος."},
        "qualifications": {"type": "array", "items": {"type": "string"},
                           "description": "Τα απαιτούμενα προσόντα, σύντομα, στα ελληνικά."},
        "deadline": {"type": ["string", "null"],
                     "description": "Προθεσμία υποβολής αιτήσεων σε μορφή YYYY-MM-DD, ή null."},
        "summary": {"type": "string", "description": "Δύο προτάσεις στα ελληνικά."},
        "fit_for_profile": {"type": "string", "enum": ["good", "partial", "poor"]},
        "fit_reason": {"type": "string", "description": "Μία πρόταση στα ελληνικά."},
    },
}

PROMPT = (
    "Είσαι βοηθός που διαβάζει ανακοινώσεις κενών θέσεων από την Επίσημη Εφημερίδα της "
    "Κυπριακής Δημοκρατίας. Απάντησε μόνο με βάση το κείμενο που σου δίνεται· μην συμπληρώνεις "
    "στοιχεία που δεν αναφέρονται. Αν κάτι λείπει, άφησέ το κενό ή null.\n\n"
    f"Προφίλ υποψηφίου για την αξιολόγηση καταλληλότητας: {PROFILE}"
)


def load_cache() -> dict:
    return json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}


def analyse(text: str, api_key: str) -> dict:
    r = requests.post(
        "https://api.openai.com/v1/responses",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": MODEL,
            "instructions": PROMPT,
            "input": text[:20000],
            "text": {"format": {"type": "json_schema", "name": "vacancy", "strict": True, "schema": SCHEMA}},
        },
        timeout=180,
    )
    if not r.ok:
        raise RuntimeError(f"OpenAI {r.status_code}: {r.text[:300]}")
    data = r.json()
    for item in data.get("output", []):
        for part in item.get("content", []):
            if part.get("type") == "output_text":
                return json.loads(part["text"])
    raise RuntimeError(f"no output_text in response: {json.dumps(data)[:300]}")


def main() -> None:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("OPENAI_API_KEY not set — skipping AI step")
        return

    results_path = HERE / "results.json"
    results = json.loads(results_path.read_text(encoding="utf-8"))
    cache = load_cache()
    done = failed = 0

    for v in results["vacancies"]:
        if v["category"] == "not_it" or not v.get("text"):
            continue
        key = f"{v['issue_number']}-{v['notice_number']}"
        if key not in cache:
            try:
                cache[key] = analyse(v["text"], api_key)
                done += 1
                print(f"  analysed {key}: {cache[key]['verdict']}")
            except Exception as e:
                failed += 1
                print(f"  failed {key}: {e}", file=sys.stderr)
                continue
        v["ai"] = cache[key]

    CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    results_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"AI: {done} analysed, {failed} failed, {len(cache)} cached ({MODEL})")


if __name__ == "__main__":
    main()
