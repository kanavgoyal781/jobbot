import re
import html
import time
import requests
from urllib.parse import urlparse, urlunparse
from concurrent.futures import ThreadPoolExecutor, as_completed

from clients import nia

DAYS_MAP = {"24 hours": 1, "1 week": 7, "1 month": 30}

_KEEP_SIGNALS = {
    "jobs", "careers", "greenhouse", "lever", "ashby", "workday",
    "smartrecruiters", "bamboohr", "jobvite", "icims", "apply",
    "opening", "position", "role", "hiring",
}
_REJECT_SIGNALS = {
    "blog", "news", "article", "salary", "review", "course",
    "bootcamp", "reddit", "medium", "youtube", "press", "docs",
    "whitepaper", "tutorial",
}


# ── Query builder ─────────────────────────────────────────────────────────────

def build_search_queries(
    candidate_profile: dict,
    role: str,
    location: str,
    h1b: bool,
) -> list[dict]:
    kw         = candidate_profile.get("search_keywords", {})
    skills     = candidate_profile.get("skills", {})
    targets    = candidate_profile.get("likely_target_roles", [])
    projects   = candidate_profile.get("skills_from_projects", [])
    industries = candidate_profile.get("industries_from_experience", [])

    role_kws  = kw.get("role_keywords", [])
    skill_kws = kw.get("skill_keywords", [])

    ml_skills  = skills.get("machine_learning", [])
    llm_skills = skills.get("llm_ai", [])
    top_skills = (ml_skills + llm_skills)[:3]

    proj_skills: list[str] = []
    for p in projects[:2]:
        proj_skills.extend(p.get("skills_shown", [])[:2])

    adjacent = [r for r in (targets + role_kws) if r.lower() != role.lower()][:3]

    first_industry = ""
    if industries:
        first_industry = industries[0].get("industry", "")

    queries: list[dict] = []

    def add(query_type: str, query: str, why: str) -> None:
        q = query.strip()
        if not q:
            return
        queries.append({
            "query_type": query_type,
            "type":       query_type,   # backward compat
            "query":      q,
            "why":        why,
        })

    # ── Role-based (3) ───────────────────────────────────────────────────────
    add("role_based",
        f"{role} jobs {location} 2025 hiring",
        f"Primary search for '{role}' in {location}")

    add("role_based",
        f'"{role}" job opening {location}',
        "Exact-phrase search to surface precise title matches")

    if adjacent:
        add("role_based",
            f"{adjacent[0]} jobs {location} 2025 hiring",
            f"Adjacent role '{adjacent[0]}' from candidate's likely target roles")

    # ── Skill-based (2) ──────────────────────────────────────────────────────
    if top_skills:
        add("skill_based",
            f"{' '.join(top_skills)} engineer jobs {location} 2025",
            f"Targets roles matching top ML/LLM skills: {', '.join(top_skills)}")

    if skill_kws:
        add("skill_based",
            f"{' '.join(skill_kws[:3])} {role} {location}",
            "Skill-keyword enriched query derived from candidate profile")

    # ── Project-based (1) ────────────────────────────────────────────────────
    if proj_skills:
        add("project_based",
            f"{' '.join(proj_skills[:3])} engineer jobs {location}",
            "Targets roles matching skills demonstrated in GitHub projects")

    # ── Industry-based (1) ───────────────────────────────────────────────────
    if first_industry:
        add("industry_based",
            f"{role} {first_industry} {location} jobs 2025",
            f"Industry-specific search for '{first_industry}' from work experience")

    # ── Visa-based (2, only when h1b=True) ───────────────────────────────────
    if h1b:
        add("visa_based",
            f"{role} H1B visa sponsorship {location} 2025",
            "Targets companies that explicitly mention H1B sponsorship")
        add("visa_based",
            f"{role} visa sponsorship {location} job hiring",
            "Broader visa sponsorship search across job boards")

    # ── Career-platform queries (4) ───────────────────────────────────────────
    add("career_platform",
        f"site:boards.greenhouse.io {role} {location}",
        "Searches Greenhouse ATS directly for active postings")

    add("career_platform",
        f"site:jobs.lever.co {role} {location}",
        "Searches Lever ATS directly for active postings")

    add("career_platform",
        f"site:jobs.ashbyhq.com {role} {location}",
        "Searches Ashby ATS directly for active postings")

    add("career_platform",
        f"site:workdayjobs.com {role}",
        "Searches Workday ATS used by large enterprises")

    # Deduplicate by query string, cap at 12
    seen_q: set[str] = set()
    final: list[dict] = []
    for q in queries:
        if q["query"] not in seen_q:
            seen_q.add(q["query"])
            final.append(q)
        if len(final) == 12:
            break

    return final


# ── Normalisation ─────────────────────────────────────────────────────────────

def normalize_job_result(raw_job: dict, query_obj: dict) -> dict:
    title = (raw_job.get("title") or raw_job.get("name") or "").strip()
    url   = (raw_job.get("url")   or raw_job.get("link") or "").strip()
    summary = (
        raw_job.get("summary") or
        raw_job.get("snippet") or
        raw_job.get("content") or
        raw_job.get("description") or ""
    ).strip()

    source = (raw_job.get("source") or raw_job.get("domain") or "").strip()
    if not source and url:
        try:
            source = urlparse(url).netloc
        except Exception:
            pass

    company = (raw_job.get("company") or raw_job.get("employer") or "").strip()
    if not company:
        for sep in (" at ", " - ", " | "):
            if sep in title:
                company = title.split(sep, 1)[1].strip()
                break
    if not company and source:
        domain_part = source.replace("www.", "").split(".")[0]
        company = domain_part.title()
    if not company:
        company = "Unknown Company"

    return {
        "title":      title,
        "company":    company,
        "url":        url,
        "summary":    summary,
        "source":     source,
        "query_type": query_obj.get("query_type", query_obj.get("type", "")),
        "query_used": query_obj.get("query", ""),
    }


# ── Junk filter ───────────────────────────────────────────────────────────────

def looks_like_job(job: dict) -> bool:
    haystack = " ".join([
        job.get("title", ""),
        job.get("url", ""),
        job.get("source", ""),
    ]).lower()

    if any(sig in haystack for sig in _REJECT_SIGNALS):
        return False
    if any(sig in haystack for sig in _KEEP_SIGNALS):
        return True
    # No strong signal either way — keep if it at least has a title and URL
    return bool(job.get("title") and job.get("url"))


# ── Deduplication ─────────────────────────────────────────────────────────────

def dedupe_jobs(jobs: list[dict]) -> list[dict]:
    seen: set[str] = set()
    unique: list[dict] = []
    for job in jobs:
        url = job.get("url", "")
        if url:
            try:
                p = urlparse(url.lower())
                key = urlunparse((p.scheme, p.netloc, p.path.rstrip("/"), "", "", ""))
            except Exception:
                key = url.lower()
        else:
            key = f"{job.get('company','').lower()}|{job.get('title','').lower()}"
        if key and key not in seen:
            seen.add(key)
            unique.append(job)
    return unique


# ── Single query (normalized) ─────────────────────────────────────────────────

def _search_single_query(query_obj: dict, days_back: int, logger) -> list[dict]:
    query_str  = query_obj["query"]
    query_type = query_obj.get("query_type", query_obj.get("type", "unknown"))
    try:
        resp       = nia.search_web(query_str, num_results=10, days_back=days_back)
        raw        = resp.get("other_content", [])
        normalized = [normalize_job_result(r, query_obj) for r in raw]
        logger.step(f"nia_search_{query_type}", "ok", f"{len(normalized)} results")
        return normalized
    except Exception as e:
        logger.step(f"nia_search_{query_type}", "failed", str(e))
        return []


# ── Remotive fallback ─────────────────────────────────────────────────────────

_REMOTIVE_CATEGORY_MAP = {
    "machine learning": "data",
    "data scientist": "data",
    "ml engineer": "data",
    "ai engineer": "data",
    "backend": "software-dev",
    "frontend": "software-dev",
    "fullstack": "software-dev",
    "devops": "devops-sysadmin",
    "product manager": "product",
    "designer": "design",
}


def _remotive_fallback(role: str, logger) -> list[dict]:
    """Free fallback: Remotive public API, no auth, no quota."""
    try:
        category = "software-dev"
        role_lower = role.lower()
        for keyword, cat in _REMOTIVE_CATEGORY_MAP.items():
            if keyword in role_lower:
                category = cat
                break

        resp = requests.get(
            "https://remotive.com/api/remote-jobs",
            params={"search": role, "limit": 50, "category": category},
            timeout=12,
        )
        resp.raise_for_status()
        raw_jobs = resp.json().get("jobs", [])

        normalized = []
        for j in raw_jobs:
            desc_html = j.get("description", "")
            desc_text = html.unescape(re.sub(r"<[^>]+>", " ", desc_html))[:500].strip()
            normalized.append({
                "title":      j.get("title", ""),
                "company":    j.get("company_name", "Unknown Company"),
                "url":        j.get("url", ""),
                "summary":    desc_text,
                "source":     "remotive.com",
                "query_type": "remotive_fallback",
                "query_used": f"Remotive: {role}",
            })

        logger.step("remotive_fallback", "ok", f"{len(normalized)} jobs from Remotive")
        return normalized
    except Exception as e:
        logger.step("remotive_fallback", "failed", str(e))
        return []


# ── Parallel search pipeline ──────────────────────────────────────────────────

def run_parallel_search(
    query_objects: list[dict],
    days_back: int,
    logger,
) -> list[dict]:
    t0: float = time.time()
    raw_all: list[dict] = []
    nia_failed = False

    # ── Phase 1: Nia parallel search ─────────────────────────────────────────
    try:
        with ThreadPoolExecutor(max_workers=3) as ex:
            futures = {ex.submit(_search_single_query, q, days_back, logger): q for q in query_objects}
            for fut in as_completed(futures):
                raw_all.extend(fut.result())
    except Exception as e:
        logger.step("nia_parallel_error", "failed", str(e))
        nia_failed = True

    logger.step("raw_result_count", "ok", f"{len(raw_all)} raw results from Nia")

    # ── Phase 2: Remotive fallback if Nia gave nothing ────────────────────────
    if not raw_all or nia_failed:
        logger.step("search_source", "skipped", "Nia returned 0 — switching to Remotive fallback")
        role_guess = next(
            (q["query"].split(" jobs")[0] for q in query_objects if "role_based" in q.get("query_type", "")),
            query_objects[0]["query"].split(" jobs")[0] if query_objects else "engineer",
        )
        raw_all = _remotive_fallback(role_guess, logger)
    else:
        logger.step("search_source", "ok", "Nia")

    job_like = [j for j in raw_all if looks_like_job(j)]
    logger.step("job_like_count", "ok",
                f"{len(job_like)} job-like (filtered {len(raw_all) - len(job_like)} junk)")

    unique = dedupe_jobs(job_like)
    logger.step("unique_job_count", "ok", f"{len(unique)} unique jobs after dedup")
    logger.step("parallel_search_time", "ok", f"{time.time()-t0:.2f}s total")

    return unique
