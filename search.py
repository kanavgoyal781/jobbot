import time
import requests
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


def _url_alive(url: str) -> bool:
    """Returns True if the URL responds with a non-4xx status."""
    try:
        r = requests.head(url, allow_redirects=True, timeout=4)
        if r.status_code == 405:
            r = requests.get(url, allow_redirects=True, timeout=4, stream=True)
            r.close()
        return r.status_code < 400
    except Exception:
        return False


def build_search_queries(
    candidate_profile: dict,
    role: str,
    location: str,
    h1b: bool,
) -> list[dict]:
    kw = candidate_profile.get("search_keywords", {})
    role_kws = " ".join(kw.get("role_keywords", [])[:3])
    skill_kws = " ".join(kw.get("skill_keywords", [])[:4])
    proj_kws = " ".join(kw.get("project_keywords", [])[:2])
    h1b_sfx = "H1B visa sponsorship" if h1b else ""

    queries = [
        {"type": "baseline",   "query": f"{role} jobs {location} {h1b_sfx} 2025 hiring"},
        {"type": "role_kw",    "query": f"{role_kws} jobs {location} 2025 hiring"},
        {"type": "skill_kw",   "query": f"{skill_kws} engineer jobs {location}"},
        {"type": "project_kw", "query": f"{proj_kws} {role} jobs {location}"},
    ]
    return [q for q in queries if q["query"].strip()]


def run_parallel_search(
    query_objects: list[dict],
    days_back: int,
    logger,
) -> list[dict]:
    """Parallel Nia searches → deduplicate → filter dead URLs → return live jobs."""
    t0 = time.time()
    raw_all: list[dict] = []

    try:
        with ThreadPoolExecutor(max_workers=3) as ex:
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

    if not unique:
        return []

    # Filter dead URLs in parallel
    t1 = time.time()
    with ThreadPoolExecutor(max_workers=10) as ex:
        futures_health = {ex.submit(_url_alive, j.get("url", "")): j for j in unique}
        live = [futures_health[fut] for fut in as_completed(futures_health) if fut.result()]
    logger.step("url_health_check", "ok", f"{len(live)}/{len(unique)} URLs alive ({time.time()-t1:.1f}s)")

    return live
