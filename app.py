import json
import time
import streamlit as st
from pathlib import Path
from backend import test_extraction
from logger import SessionLogger
from validation import ResumeUploadInput, LinkedInUploadInput, GitHubInput
from extraction import _extract_text, _fetch_github_deep
from profile import build_candidate_profile
from search import build_search_queries, run_parallel_search, DAYS_MAP
from ranking import score_jobs

st.set_page_config(page_title="Job Bot", page_icon="🔍", layout="centered")
st.title("Job Bot")
st.markdown("**Kanav's Assistant** — powered by Nia")

# ====================== UPLOADS ======================
st.header("Upload your info")

col1, col2 = st.columns(2)
with col1:
    resume_file = st.file_uploader("📄 Resume — PDF or TXT (required)", type=["pdf", "txt"])
with col2:
    linkedin_file = st.file_uploader("🔗 LinkedIn Export PDF (required)", type=["pdf"])

github_link = st.text_input(
    "🐙 GitHub Profile (optional)",
    placeholder="https://github.com/kanavgoyal781  or just  kanavgoyal781",
)

# ====================== FILTERS ======================
st.header("Job Preferences")

role = st.text_input("Role you are looking for", placeholder="Senior Backend Engineer")

col3, col4 = st.columns(2)
with col3:
    location = st.selectbox(
        "Location",
        ["Remote", "San Francisco", "New York", "Seattle", "Austin", "Anywhere in USA"],
    )
with col4:
    time_live = st.selectbox(
        "Job posted in last",
        ["24 hours", "1 week", "1 month"],
        index=1,
    )

h1b = False
st.caption("🔬 H1B sponsorship detection — coming soon (Beta)")

# ====================== BUTTONS ======================
col_btn1, col_btn2 = st.columns([2, 1])
with col_btn1:
    search_clicked = st.button("🔍 Find My Jobs", type="primary", use_container_width=True)
with col_btn2:
    test_clicked = st.button("🧪 Test Indexing Only", use_container_width=True)

# ── Test extraction (no job search) ──────────────────────────────────────────
if test_clicked:
    if not resume_file:
        st.error("Resume is required.")
        st.stop()
    if not linkedin_file:
        st.error("LinkedIn PDF is required.")
        st.stop()

    resume_path = Path("temp_resume.pdf")
    resume_path.write_bytes(resume_file.getvalue())
    linkedin_path = Path("temp_linkedin.pdf")
    linkedin_path.write_bytes(linkedin_file.getvalue())

    with st.spinner("Extracting and validating your profile..."):
        try:
            r = test_extraction(str(resume_path), str(linkedin_path), github_link.strip() or None)
        except ValueError as e:
            st.error(str(e))
            st.stop()

    st.success(f"✅ Extraction complete — Session `{r['session_id']}`")

    # ── Raw source stats (collapsed by default) ──────────────────────────────
    with st.expander("📄 Resume", expanded=False):
        info = r["resume"]
        st.write(f"**Characters extracted:** {info['chars']:,}  •  **Sections found:** {info['sections_found']}")
        st.code(info["preview"], language=None)

    with st.expander("🔗 LinkedIn", expanded=False):
        info = r["linkedin"]
        st.write(f"**Characters extracted:** {info['chars']:,}  •  **Sections found:** {info['sections_found']}")
        st.code(info["preview"], language=None)

    with st.expander("🐙 GitHub", expanded=False):
        gh = r["github"]
        if gh.get("repos"):
            st.write(f"**Username:** {gh.get('username')}  •  **Repos:** {', '.join(gh['repos'])}")
            st.write(f"**Total chars:** {gh['total_chars']:,}  •  **Files fetched:** {len(gh.get('files_indexed', []))}")
            st.code(gh["preview"], language=None)
        elif gh.get("warning"):
            st.warning(f"GitHub skipped: {gh['warning']}")
        else:
            st.info("No GitHub URL provided.")

    resume_chars = r["resume"]["chars"]
    linkedin_chars = r["linkedin"]["chars"]
    github_chars = r["github"].get("total_chars", 0)
    total = resume_chars + linkedin_chars + github_chars
    st.caption(f"Total profile: {total:,} chars (Resume {resume_chars:,} + LinkedIn {linkedin_chars:,} + GitHub {github_chars:,})")

    # ── Candidate Profile ─────────────────────────────────────────────────────
    st.subheader("🧠 Candidate Profile")
    cp = r.get("candidate_profile", {})

    if not cp:
        st.warning("Could not build candidate profile — see Step Log for details.")
    else:
        with st.expander("1. Candidate Summary", expanded=True):
            st.write(cp.get("candidate_summary", "—"))

        with st.expander("2. Highest Education", expanded=True):
            edu = cp.get("highest_education", {})
            col1, col2 = st.columns(2)
            with col1:
                st.write(f"**Degree:** {edu.get('degree', '—')}")
                st.write(f"**Field:** {edu.get('field', '—')}")
                st.write(f"**School:** {edu.get('school', '—')}")
            with col2:
                st.write(f"**Graduation:** {edu.get('graduation_year', '—')}")
                st.write(f"**Confidence:** {edu.get('confidence', '—')}")

        with st.expander("3. Estimated Years of Experience", expanded=True):
            exp = cp.get("estimated_years_of_experience", {})
            st.write(f"**Years:** {exp.get('years', '—')}  •  **Confidence:** {exp.get('confidence', '—')}")
            st.write(f"**Reason:** {exp.get('reason', '—')}")

        with st.expander("4. Companies Worked At", expanded=True):
            for c in cp.get("companies_worked_at", []):
                with st.container(border=True):
                    st.write(f"**{c.get('company', '?')}** — {c.get('role', '?')}")
                    st.caption(f"Industry: {c.get('industry', '?')}  •  Evidence: {c.get('evidence', '?')}")

        with st.expander("5. Industries From Experience", expanded=False):
            for ind in cp.get("industries_from_experience", []):
                st.write(f"**{ind.get('industry', '?')}** — {ind.get('why_relevant', '?')}")
                st.caption(f"Evidence: {ind.get('evidence', '?')}")

        with st.expander("6. Skills", expanded=True):
            skills = cp.get("skills", {})
            labels = {
                "programming_languages": "Programming Languages",
                "machine_learning": "Machine Learning",
                "data_science_analytics": "Data Science & Analytics",
                "data_engineering": "Data Engineering",
                "llm_ai": "LLM / AI",
                "cloud_tools_platforms": "Cloud & Platforms",
                "domain_skills": "Domain Skills",
            }
            for key, label in labels.items():
                items = skills.get(key, [])
                if items:
                    st.write(f"**{label}:** {', '.join(items)}")

        with st.expander("7. Skills From Projects (GitHub)", expanded=True):
            for proj in cp.get("skills_from_projects", []):
                with st.container(border=True):
                    st.write(f"**{proj.get('project_name', '?')}**")
                    st.write(f"Skills: {', '.join(proj.get('skills_shown', []))}")
                    st.write(f"Relevance: {', '.join(proj.get('industry_relevance', []))}")
                    st.caption(proj.get("evidence", ""))

        with st.expander("8. Strongest Profile Signals", expanded=True):
            for sig in cp.get("strongest_profile_signals", []):
                with st.container(border=True):
                    st.write(f"**{sig.get('signal', '?')}**")
                    st.write(sig.get("why_it_matters_for_jobs", ""))
                    st.caption(f"Evidence: {sig.get('evidence', '?')}")

        with st.expander("9. Likely Target Roles", expanded=True):
            roles = cp.get("likely_target_roles", [])
            st.write(", ".join(roles) if roles else "—")

        with st.expander("10. Search Keywords", expanded=False):
            kw = cp.get("search_keywords", {})
            kw_labels = {
                "role_keywords": "Role",
                "skill_keywords": "Skill",
                "industry_keywords": "Industry",
                "project_keywords": "Project",
                "education_keywords": "Education",
            }
            for key, label in kw_labels.items():
                items = kw.get(key, [])
                if items:
                    st.write(f"**{label}:** {', '.join(items)}")

        with st.expander("11. Possible Weaknesses or Gaps", expanded=False):
            gaps = cp.get("possible_weaknesses_or_gaps", [])
            if gaps:
                for g in gaps:
                    st.write(f"**{g.get('gap', '?')}** — {g.get('why_it_might_matter', '?')}")
            else:
                st.write("None identified.")

    with st.expander("🔍 Step Log", expanded=False):
        for step in r["log"].get("steps", []):
            icon = {"ok": "✅", "failed": "❌", "skipped": "⚠️"}.get(step["status"], "•")
            st.markdown(f"{icon} **{step['step']}** — {step['detail']}")

    st.download_button(
        "📥 Download Session Log",
        data=json.dumps(r["log"], indent=2),
        file_name=f"jobbot_{r['session_id']}.json",
        mime="application/json",
    )
    st.stop()

# ── Full job search ───────────────────────────────────────────────────────────
if search_clicked:

    if not resume_file:
        st.error("Resume is required.")
        st.stop()
    if not linkedin_file:
        st.error("LinkedIn PDF is required. Export it from LinkedIn → Me → Settings & Privacy → Data Privacy → Get a copy of your data.")
        st.stop()
    if not role.strip():
        st.error("Please enter the role you are looking for.")
        st.stop()

    resume_path = Path("temp_resume.pdf")
    resume_path.write_bytes(resume_file.getvalue())
    linkedin_path = Path("temp_linkedin.pdf")
    linkedin_path.write_bytes(linkedin_file.getvalue())

    logger = SessionLogger()
    jobs: list[dict] = []
    session_id = logger.session_id
    log: dict = {}
    candidate_profile: dict = {}
    github_repos: list[str] = []

    with st.status("Running Job Bot...", expanded=True) as status:
        try:
            # ── 1. Resume ─────────────────────────────────────────────────────
            st.write("📄 Parsing resume...")
            resume_input = ResumeUploadInput(file_path=str(resume_path))
            resume_text = _extract_text(Path(resume_input.file_path))
            logger.step("resume_validation", "ok", f"{len(resume_text)} chars")
            st.write(f"✅ Resume — {len(resume_text):,} chars")

            # ── 2. LinkedIn ───────────────────────────────────────────────────
            st.write("🔗 Parsing LinkedIn export...")
            linkedin_input = LinkedInUploadInput(file_path=str(linkedin_path))
            linkedin_text = _extract_text(Path(linkedin_input.file_path))
            logger.step("linkedin_validation", "ok", f"{len(linkedin_text)} chars")
            st.write(f"✅ LinkedIn — {len(linkedin_text):,} chars")

            # ── 3. GitHub ─────────────────────────────────────────────────────
            github_text = ""
            if github_link.strip():
                st.write(f"🐙 Fetching GitHub repos for `{github_link.strip()}`...")
                t_gh = time.time()
                github_input = GitHubInput(profile_url=github_link.strip())
                github_repos, github_text = _fetch_github_deep(github_input.username, logger)
                st.write(f"✅ GitHub — {len(github_repos)} repos, {len(github_text):,} chars ({time.time()-t_gh:.1f}s)")

            # ── 4. Candidate profile fingerprint ─────────────────────────────
            profile_parts = [f"=== RESUME ===\n{resume_text}", f"=== LINKEDIN PROFILE ===\n{linkedin_text}"]
            if github_text:
                profile_parts.append(f"=== GITHUB PROJECTS ===\n{github_text}")
            profile_summary = "\n\n".join(profile_parts)
            logger.step("profile_build", "ok", f"{len(profile_summary)} chars")

            st.write("🧠 Extracting candidate profile fingerprint...")
            t_cp = time.time()
            candidate_profile = build_candidate_profile(profile_summary, logger)
            preview = (candidate_profile.get("candidate_summary") or "")[:90]
            st.write(f"✅ Profile fingerprint — {time.time()-t_cp:.1f}s")
            if preview:
                st.caption(f"_{preview}…_")

            # ── 5. Build search queries ───────────────────────────────────────
            st.write("🔍 Building targeted search queries from your profile...")
            queries = build_search_queries(candidate_profile, role, location, h1b)
            logger.step("query_generation", "ok", f"{len(queries)} queries")
            for q in queries:
                st.write(f"   → `{q['query'][:90]}`")

            # ── 6. Parallel Nia search ────────────────────────────────────────
            st.write(f"🌐 Running {len(queries)} searches in parallel via Nia...")
            t_search = time.time()
            days_back = DAYS_MAP.get(time_live, 7)
            raw_jobs = run_parallel_search(queries, days_back, logger)
            st.write(f"✅ Search — {len(raw_jobs)} unique listings ({time.time()-t_search:.1f}s)")

            if not raw_jobs:
                status.update(label="❌ No listings found", state="error")
                st.error("Nia returned no job listings. Try a different role or broaden location.")
                st.stop()

            # ── 7. Claude scoring ─────────────────────────────────────────────
            st.write(f"🤖 Scoring {len(raw_jobs)} jobs with Claude Haiku...")
            t_score = time.time()
            scored = score_jobs(raw_jobs, candidate_profile, logger)
            st.write(f"✅ Scoring done — {len(scored)} jobs ranked ({time.time()-t_score:.1f}s)")

            jobs = scored[:7]

            if not jobs:
                status.update(label="❌ No matches after H1B filter", state="error")
                st.error("No jobs survived the H1B filter. Try unchecking H1B or changing the role.")
                st.stop()

            log = logger.get_log()
            logger.success()
            status.update(
                label=f"✅ Found {len(jobs)} matches  •  Session `{session_id}`",
                state="complete",
            )

        except ValueError as e:
            logger.fail(str(e))
            status.update(label="❌ Failed", state="error")
            st.error(str(e))
            st.caption("Session logged to `logs/dead_letter.jsonl`.")
            st.stop()
        except Exception as e:
            logger.fail(str(e))
            status.update(label="❌ Unexpected error", state="error")
            st.error(f"Unexpected error: {e}")
            st.stop()

    # ── Profile summary + session bar ────────────────────────────────────────
    if candidate_profile.get("candidate_summary"):
        st.caption(candidate_profile["candidate_summary"][:220])

    col_s1, col_s2 = st.columns([3, 1])
    with col_s1:
        st.caption(f"Session ID: `{session_id}`  •  Log: `logs/{session_id}.json`")
    with col_s2:
        st.download_button(
            "📥 Download Log",
            data=json.dumps(log, indent=2),
            file_name=f"jobbot_{session_id}.json",
            mime="application/json",
        )

    with st.expander("🔍 Session Step Log", expanded=False):
        for step in log.get("steps", []):
            icon = {"ok": "✅", "failed": "❌", "skipped": "⚠️", "info": "ℹ️"}.get(step["status"], "•")
            st.markdown(f"{icon} **{step['step']}** — {step['detail']}")

    with st.expander("🔎 Generated Search Queries", expanded=False):
        for q in queries:
            st.markdown(f"**`{q['query_type']}`** — {q['query']}")
            st.caption(q.get("why", ""))

    # ── Job results ───────────────────────────────────────────────────────────
    st.subheader(f"Top {len(jobs)} Job Matches")
    st.caption("⚠️ Direct links may expire — use the LinkedIn button to find the live posting if Apply → is broken.")

    for job in jobs:
        title = job.get("title", "Unknown Role")
        company = job.get("company", "Unknown Company")
        score = job.get("match_score", 0)
        why = job.get("why", "")
        url = job.get("url", "")
        h1b_likely = job.get("h1b_likely", False)

        with st.container(border=True):
            col_a, col_b = st.columns([5, 1])
            with col_a:
                st.subheader(title)
                badge_parts = [f"**{company}**", location, f"Posted within {time_live}"]
                st.caption("  •  ".join(badge_parts))
                st.progress(score / 100)
                st.write(f"**Match: {score}%**")
                st.write(f"💡 *{why}*")
            with col_b:
                from urllib.parse import quote_plus
                linkedin_url = f"https://www.linkedin.com/jobs/search/?keywords={quote_plus(title + ' ' + company)}&location={quote_plus(location)}"
                if url:
                    st.link_button("Apply →", url, use_container_width=True)
                st.link_button("🔗 LinkedIn", linkedin_url, use_container_width=True)

st.caption("Built for OpenClaw Hackathon  •  Nia as the core brain  •  Eragon × Nozomio × AgentMail")
