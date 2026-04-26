# Job Bot — AI Job Scout

Powered by **Nia** (Nozomio) + **Claude Haiku** (Anthropic).

---

## What it is

Job Bot is a personal AI job scout that finds and ranks the most relevant job openings for you based on your actual experience, skills, and projects — not just keywords. Upload your resume, LinkedIn export, and GitHub profile, tell it what role you want, and it returns your top 7 matches with a match score and a one-line explanation of why each role fits.

## The problem it solves

Job searching is manual, slow, and generic. Most job boards return hundreds of irrelevant results and have no idea who you actually are. Job Bot flips this: it first builds a deep candidate fingerprint from everything you share (resume, LinkedIn, GitHub code), then searches across multiple job platforms in parallel, and finally uses an AI recruiter to score each listing against your real profile — surfacing the roles most likely to actually want you.

## How it works

1. **Profile extraction** — Claude reads your resume, LinkedIn, and GitHub repos to extract a structured fingerprint: skills, years of experience, companies, strongest signals, and search keywords.
2. **Smart parallel search** — up to 12 targeted queries run simultaneously across Nia web search, Greenhouse, Lever, and Ashby ATS platforms. If Nia's quota is hit, it automatically falls back to Remotive, then Arbeit Now — so results always come back.
3. **AI scoring** — Claude scores every listing against your fingerprint, penalises seniority mismatches (won't recommend a Staff role to a 3-year engineer), and returns your top 7 ranked by genuine fit.

---

## Features

- Deep GitHub indexing — reads actual code, not just READMEs
- 12 parallel search queries across role, skill, project, and platform dimensions
- Three-tier search fallback: Nia → Remotive → Arbeit Now
- Seniority-aware scoring — matches level to your years of experience
- Live progress with per-step timing
- LinkedIn fallback button on every result card
- 🔬 H1B sponsorship detection — coming soon (Beta)

## How to use

```bash
pip install -r requirements.txt

# Add keys to .env
NIA_API_KEY=...
GITHUB_TOKEN=...   # optional but recommended — prevents rate limiting

streamlit run app.py
```

Upload your **resume PDF**, **LinkedIn export PDF** (LinkedIn → Settings → Data Privacy → Get a copy of your data), and optionally your GitHub URL. Enter the role and location, hit **Find My Jobs**.

## Built for

OpenClaw Hackathon — Eragon × Nozomio × AgentMail
