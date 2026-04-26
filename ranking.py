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
    "why": "One sentence explaining why this candidate is a strong fit.",
    "h1b_likely": true,
    "url": "job url"
  }}
]

Rules:
- match_score 0-100 based on genuine skill/experience overlap with the profile
- h1b_likely = true for large companies, well-funded startups, or companies known to sponsor H1B
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
    """Hard-filters to H1B-likely jobs before final ranking. Falls back to unfiltered if none pass."""
    if not h1b:
        return scored_jobs

    filtered = [j for j in scored_jobs if j.get("h1b_likely", False)]
    if not filtered:
        logger.step("h1b_filter", "skipped", "No H1B-likely jobs found — returning unfiltered")
        return scored_jobs

    logger.step("h1b_filter", "ok", f"{len(filtered)} H1B-likely jobs pass filter")
    return filtered
