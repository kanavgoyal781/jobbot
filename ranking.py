import re
import json
import time
from clients import _claude


def score_jobs(raw_jobs: list[dict], candidate_profile: dict, logger) -> list[dict]:
    """Scores all raw_jobs against a compact profile fingerprint. Returns sorted list."""
    if not raw_jobs:
        return []

    t0 = time.time()
    profile_compact = json.dumps({
        "summary":          candidate_profile.get("candidate_summary", ""),
        "years_experience": candidate_profile.get("estimated_years_of_experience", {}).get("years"),
        "skills":           candidate_profile.get("skills", {}),
        "companies":        [c["company"] for c in candidate_profile.get("companies_worked_at", [])],
        "signals":          [s["signal"] for s in candidate_profile.get("strongest_profile_signals", [])],
        "target_roles":     candidate_profile.get("likely_target_roles", []),
    }, indent=2)

    capped = raw_jobs[:20]
    jobs_block = "\n\n".join(
        f"JOB {i+1}:\nTitle: {j.get('title','')}\nURL: {j.get('url','')}\n"
        f"Description: {j.get('summary','')[:400]}"
        for i, j in enumerate(capped)
    )

    years = candidate_profile.get("estimated_years_of_experience", {}).get("years") or 0
    # Map years → appropriate seniority band
    if years <= 2:
        seniority_note = "Candidate is early-career (0-2 yrs). Prefer Junior/Mid roles. Heavily penalise Staff/Principal/Distinguished/12+ yr roles."
    elif years <= 5:
        seniority_note = "Candidate is mid-level (3-5 yrs). Prefer Mid/Senior roles. Penalise Staff/Principal/Lead roles that require 8+ years."
    elif years <= 8:
        seniority_note = "Candidate is senior (6-8 yrs). Prefer Senior/Lead roles. Penalise Staff/Distinguished roles requiring 10+ years."
    else:
        seniority_note = "Candidate is experienced (8+ yrs). Senior/Staff roles are appropriate."

    prompt = f"""You are an expert technical recruiter. Score each job listing against this candidate profile.

CANDIDATE PROFILE:
{profile_compact}

JOB LISTINGS:
{jobs_block}

Return ONLY a valid JSON array sorted by match_score descending (no markdown, no explanation):
[
  {{
    "title": "exact job title",
    "company": "company name",
    "match_score": 87,
    "why": "One sentence explaining the fit based on actual skills and experience.",
    "h1b_likely": true,
    "url": "job url"
  }}
]

Rules:
- match_score 0-100 based on genuine skill/experience overlap. If profile is missing, score max 20.
- Seniority: {seniority_note}
- h1b_likely = true for large companies, well-funded startups, or companies known to sponsor H1B
- why must reference specific skills or experience from the profile, not generic statements
- Include all {len(capped)} jobs
- Return ONLY the JSON array, nothing else"""

    logger.step("claude_scoring", "ok", f"Scoring {len(capped)} jobs")
    msg = _claude.messages.create(
        model="claude-haiku-4-5",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    answer = msg.content[0].text.strip()
    logger.step("claude_scoring_time", "ok", f"{time.time()-t0:.2f}s")

    if answer.startswith("```"):
        answer = re.sub(r"^```(?:json)?\s*", "", answer)
        answer = re.sub(r"\s*```$", "", answer)

    json_match = re.search(r"\[.*\]", answer, re.DOTALL)
    if not json_match:
        logger.step("claude_parse", "failed", f"No JSON array: {answer[:200]}")
        return []

    try:
        scored = json.loads(json_match.group())
        logger.step("claude_parse", "ok", f"Parsed {len(scored)} scored jobs")
        return sorted(scored, key=lambda j: j.get("match_score", 0), reverse=True)
    except Exception as e:
        logger.step("claude_parse", "failed", str(e))
        return []


def apply_h1b_filter(scored_jobs: list[dict], h1b: bool, logger) -> list[dict]:
    """No hard filtering — H1B detection is heuristic only. Always returns full ranked list."""
    h1b_count = len([j for j in scored_jobs if j.get("h1b_likely", False)])
    logger.step("h1b_badge", "ok", f"{h1b_count}/{len(scored_jobs)} marked H1B-likely (heuristic)")
    return scored_jobs
