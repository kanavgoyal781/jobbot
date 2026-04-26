import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from clients import nia

DAYS_MAP = {"24 hours": 1, "1 week": 7, "1 month": 30}


def _search_single_query(query_obj: dict, days_back: int, logger) -> list[dict]:
    query_str = query_obj["query"]
    query_type = query_obj["type"]
    try:
        resp = nia.search_web(query_str, num_results=10, days_back=days_back)
        results = resp.get("other_content", [])
        for r in results:
            r["_query_type"] = query_type
            r["_query_used"] = query_str
        logger.step(f"nia_search_{query_type}", "ok", f"{len(results)} results")
        return results
    except Exception as e:
        logger.step(f"nia_search_{query_type}", "failed", str(e))
        return []



def build_search_queries(
    candidate_profile: dict,
    role: str,
    location: str,
    h1b: bool,
) -> list[dict]:
    kw       = candidate_profile.get("search_keywords", {})
    skills   = candidate_profile.get("skills", {})
    targets  = candidate_profile.get("likely_target_roles", [])

    role_kws  = kw.get("role_keywords", [])
    skill_kws = kw.get("skill_keywords", [])
    ml_skills = skills.get("machine_learning", [])
    llm_skills = skills.get("llm_ai", [])
    top_skills = " ".join((ml_skills + llm_skills)[:3])

    h1b_sfx = "H1B visa sponsorship" if h1b else ""

    # Alternative role titles drawn from candidate profile
    alt_roles = [r for r in (role_kws + targets) if r.lower() != role.lower()][:4]

    raw = [
        # Core role — multiple phrasings
        f"{role} jobs {location} 2025 hiring",
        f'"{role}" {location} job opening apply now',
        f"{role} {h1b_sfx} {location} 2025",

        # Alt role titles
        *[f"{r} jobs {location} 2025" for r in alt_roles[:3]],

        # Skill-targeted
        f"{top_skills} engineer jobs {location} 2025 hiring",
        f"{' '.join(skill_kws[:3])} {role} {location}",

        # Job board phrasing
        f"{role} remote job apply {location} 2025",
        f"{role} {location} new job posting this week",

        # H1B explicit
        f"{role} visa sponsorship {location} job 2025",
        f"{role} {location} H1B sponsor hiring now",
    ]

    seen, queries = set(), []
    for i, q in enumerate(raw):
        q = q.strip()
        if q and q not in seen:
            seen.add(q)
            queries.append({"type": f"q{i+1}", "query": q})
        if len(queries) == 12:
            break

    return queries


def run_parallel_search(
    query_objects: list[dict],
    days_back: int,
    logger,
) -> list[dict]:
    """Parallel Nia searches → deduplicate → filter dead URLs → return live jobs."""
    t0 = time.time()
    raw_all: list[dict] = []

    try:
        with ThreadPoolExecutor(max_workers=6) as ex:
            futures = {ex.submit(_search_single_query, q, days_back, logger): q for q in query_objects}
            for fut in as_completed(futures):
                raw_all.extend(fut.result())
        logger.step("parallel_search", "ok", f"{time.time()-t0:.2f}s — {len(raw_all)} raw results")
    except Exception as e:
        logger.step("parallel_search_fallback", "skipped", str(e))
        for q in query_objects:
            raw_all.extend(_search_single_query(q, days_back, logger))

    # Deduplicate by URL
    seen: set[str] = set()
    unique: list[dict] = []
    for j in raw_all:
        url = j.get("url", "")
        if url and url not in seen:
            seen.add(url)
            unique.append(j)
    logger.step("dedup", "ok", f"{len(unique)} unique from {len(raw_all)} raw")
    return unique
