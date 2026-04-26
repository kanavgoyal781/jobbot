from pathlib import Path
from typing import Optional

from logger import SessionLogger
from validation import ResumeUploadInput, LinkedInUploadInput, GitHubInput, RESUME_SECTIONS, LINKEDIN_SECTIONS
from extraction import _extract_text, _fetch_github_deep
from profile import build_candidate_profile
from search import build_search_queries, run_parallel_search, DAYS_MAP
from ranking import score_jobs, apply_h1b_filter


def test_extraction(
    resume_path: str,
    linkedin_path: str,
    github_url: Optional[str],
) -> dict:
    """Validates and extracts everything. No job search, no quota used."""
    logger = SessionLogger()
    result: dict = {"session_id": logger.session_id, "log": None}

    # Resume (mandatory)
    try:
        resume_input = ResumeUploadInput(file_path=resume_path)
        resume_text = _extract_text(Path(resume_input.file_path))
        lower = resume_text.lower()
        sections_found = [s for s in RESUME_SECTIONS if s in lower]
        logger.step("resume_validation", "ok", f"{len(resume_text)} chars, sections: {sections_found}")
        result["resume"] = {
            "chars": len(resume_text),
            "sections_found": sections_found,
            "preview": resume_text[:800].strip(),
        }
    except Exception as e:
        logger.step("resume_validation", "failed", str(e))
        logger.fail(str(e))
        result["log"] = logger.get_log()
        raise ValueError(f"Resume: {e}")

    # LinkedIn (mandatory)
    try:
        linkedin_input = LinkedInUploadInput(file_path=linkedin_path)
        linkedin_text = _extract_text(Path(linkedin_input.file_path))
        lower = linkedin_text.lower()
        sections_found = [s for s in LINKEDIN_SECTIONS if s in lower]
        logger.step("linkedin_validation", "ok", f"{len(linkedin_text)} chars, sections: {sections_found}")
        result["linkedin"] = {
            "chars": len(linkedin_text),
            "sections_found": sections_found,
            "preview": linkedin_text[:800].strip(),
        }
    except Exception as e:
        logger.step("linkedin_validation", "failed", str(e))
        logger.fail(str(e))
        result["log"] = logger.get_log()
        raise ValueError(f"LinkedIn: {e}")

    # GitHub (optional)
    github_text = ""
    result["github"] = {"repos": [], "total_chars": 0, "files_indexed": []}
    if github_url and github_url.strip():
        try:
            github_input = GitHubInput(profile_url=github_url.strip())
            logger.step("github_validation", "ok", f"Username: {github_input.username}")
            repos, github_text = _fetch_github_deep(github_input.username, logger)
            result["github"] = {
                "username": github_input.username,
                "repos": repos,
                "total_chars": len(github_text),
                "preview": github_text[:1000].strip(),
                "files_indexed": [
                    s.split("--- ")[1].split(" ---")[0]
                    for s in github_text.split("\n")
                    if s.startswith("--- ") and s.endswith(" ---")
                ],
            }
            logger.step("github_indexing", "ok", f"Repos: {repos}, {len(github_text)} chars")
        except Exception as e:
            logger.step("github_validation", "skipped", str(e))
            result["github"]["warning"] = str(e)

    profile_parts = [f"=== RESUME ===\n{resume_text}", f"=== LINKEDIN PROFILE ===\n{linkedin_text}"]
    if github_text:
        profile_parts.append(f"=== GITHUB PROJECTS ===\n{github_text}")
    profile_summary = "\n\n".join(profile_parts)
    result["candidate_profile"] = build_candidate_profile(profile_summary, logger)

    logger.success()
    result["log"] = logger.get_log()
    return result


def run_job_bot(
    resume_path: str,
    linkedin_path: str,
    github_url: Optional[str],
    role: str,
    location: str,
    h1b: bool,
    time_live: str,
) -> dict:
    """Main pipeline. Raises ValueError with a clear message on failure (logged to DLQ)."""
    logger = SessionLogger()

    # Step 1: Resume
    try:
        resume_input = ResumeUploadInput(file_path=resume_path)
        resume_text = _extract_text(Path(resume_input.file_path))
        logger.step("resume_validation", "ok", f"{len(resume_text)} chars extracted")
    except Exception as e:
        reason = f"Resume validation failed: {e}"
        logger.step("resume_validation", "failed", str(e))
        logger.fail(reason)
        raise ValueError(reason)

    # Step 2: LinkedIn
    try:
        linkedin_input = LinkedInUploadInput(file_path=linkedin_path)
        linkedin_text = _extract_text(Path(linkedin_input.file_path))
        logger.step("linkedin_validation", "ok", f"{len(linkedin_text)} chars extracted")
    except Exception as e:
        reason = f"LinkedIn validation failed: {e}"
        logger.step("linkedin_validation", "failed", str(e))
        logger.fail(reason)
        raise ValueError(reason)

    # Step 3: GitHub (optional)
    github_repos: list[str] = []
    github_text = ""
    if github_url and github_url.strip():
        try:
            github_input = GitHubInput(profile_url=github_url.strip())
            logger.step("github_validation", "ok", f"Username: {github_input.username}")
            github_repos, github_text = _fetch_github_deep(github_input.username, logger)
            logger.step("github_indexing", "ok", f"Repos indexed: {github_repos}")
        except Exception as e:
            logger.step("github_validation", "skipped", f"GitHub skipped (optional): {e}")

    # Step 4: Assemble profile text + build fingerprint
    profile_parts = [f"=== RESUME ===\n{resume_text}", f"=== LINKEDIN PROFILE ===\n{linkedin_text}"]
    if github_text:
        profile_parts.append(f"=== GITHUB PROJECTS ===\n{github_text}")
    profile_summary = "\n\n".join(profile_parts)
    logger.step("profile_build", "ok", f"Total: {len(profile_summary)} chars from {len(profile_parts)} sources")

    candidate_profile = build_candidate_profile(profile_summary, logger)

    # Step 5: Smart parallel search → score → H1B filter → top 7
    try:
        days_back = DAYS_MAP.get(time_live, 7)
        queries = build_search_queries(candidate_profile, role, location, h1b)
        logger.step("query_generation", "ok", f"{len(queries)} queries built")

        raw_jobs = run_parallel_search(queries, days_back, logger)
        if not raw_jobs:
            logger.step("job_search", "failed", "No jobs from Nia")
            logger.fail("Job search returned no results")
            raise ValueError("Job search returned no results. Try a different role or location.")

        scored = score_jobs(raw_jobs, candidate_profile, logger)
        jobs = apply_h1b_filter(scored, h1b, logger)[:7]

        if not jobs:
            logger.step("job_results", "failed", "No jobs after filter")
            logger.fail("No jobs survived H1B filter")
            raise ValueError("No jobs found after H1B filter. Try unchecking H1B or changing role.")

        logger.step("job_results", "ok", f"{len(jobs)} final jobs")
    except ValueError:
        raise
    except Exception as e:
        reason = f"Job search failed: {e}"
        logger.step("job_search", "failed", str(e))
        logger.fail(reason)
        raise ValueError(reason)

    logger.success()
    return {
        "session_id":        logger.session_id,
        "jobs":              jobs,
        "candidate_profile": candidate_profile,
        "github_repos":      github_repos,
        "log":               logger.get_log(),
    }
