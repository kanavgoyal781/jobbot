import re
import json
from clients import _claude

_PROFILE_SCHEMA = """{
  "candidate_summary": "short 3-5 sentence summary of the candidate",
  "highest_education": {
    "degree": "",
    "field": "",
    "school": "",
    "graduation_year": "",
    "confidence": "high/medium/low"
  },
  "estimated_years_of_experience": {
    "years": 0,
    "confidence": "high/medium/low",
    "reason": ""
  },
  "companies_worked_at": [
    {
      "company": "",
      "role": "",
      "industry": "",
      "evidence": ""
    }
  ],
  "industries_from_experience": [
    {
      "industry": "",
      "why_relevant": "",
      "evidence": ""
    }
  ],
  "skills": {
    "programming_languages": [],
    "machine_learning": [],
    "data_science_analytics": [],
    "data_engineering": [],
    "llm_ai": [],
    "cloud_tools_platforms": [],
    "domain_skills": []
  },
  "skills_from_projects": [
    {
      "project_name": "",
      "skills_shown": [],
      "industry_relevance": [],
      "evidence": ""
    }
  ],
  "strongest_profile_signals": [
    {
      "signal": "",
      "why_it_matters_for_jobs": "",
      "evidence": ""
    }
  ],
  "likely_target_roles": [],
  "search_keywords": {
    "role_keywords": [],
    "skill_keywords": [],
    "industry_keywords": [],
    "project_keywords": [],
    "education_keywords": []
  },
  "possible_weaknesses_or_gaps": [
    {
      "gap": "",
      "why_it_might_matter": ""
    }
  ]
}"""


def build_candidate_profile(profile_summary: str, logger) -> dict:
    prompt = f"""Extract a structured candidate profile from the text below.

Rules:
1. Extract only what is supported by evidence in the text. Do not invent anything.
2. Do not invent companies, degrees, skills, or years of experience.
3. If something is unclear, set confidence to "low" and explain why in the reason field.
4. For years of experience, estimate from work/project dates. Do not overcount overlapping roles.
5. For industries, infer from company domains and project content.
6. For skills_from_projects, focus on skills demonstrated by GitHub/project content, not just skills listed in the resume.
7. Return only valid JSON matching the schema exactly. No markdown, no explanation.

CANDIDATE PROFILE TEXT:
{profile_summary[:15000]}

RETURN THIS EXACT JSON SCHEMA FILLED IN:
{_PROFILE_SCHEMA}"""

    logger.step("candidate_profile_build", "ok", "Calling Claude to extract candidate profile")
    try:
        msg = _claude.messages.create(
            model="claude-haiku-4-5",
            max_tokens=4096,
            system="You are a precise candidate profile extractor. Return only valid JSON, no markdown, no explanation.",
            messages=[{"role": "user", "content": prompt}],
        )
        answer = msg.content[0].text.strip()
        if answer.startswith("```"):
            answer = re.sub(r"^```(?:json)?\s*", "", answer)
            answer = re.sub(r"\s*```$", "", answer)
        json_match = re.search(r"\{.*\}", answer, re.DOTALL)
        if not json_match:
            raise ValueError(f"No JSON object found in response: {answer[:200]}")
        profile = json.loads(json_match.group())
        logger.step("candidate_profile_parse", "ok", f"Parsed {len(profile)} top-level keys")
        return profile
    except Exception as e:
        logger.step("candidate_profile_parse", "failed", str(e))
        return {}
