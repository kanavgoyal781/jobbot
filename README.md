# Job Bot — AI Job Scout

Powered by **Nia** (Nozomio) + **Claude Haiku**. Upload your resume and LinkedIn, and it finds, scores, and ranks the best job matches for you — with H1B filtering built in.

---

## What it does

1. Parses your resume, LinkedIn export, and GitHub profile
2. Builds a structured candidate fingerprint using Claude
3. Runs 4 targeted job searches in parallel via Nia
4. Scores every listing against your actual skills and experience
5. Filters to H1B-sponsoring companies before final ranking
6. Returns your top 7 matches with match score and reasoning

## Features

- **Smart queries** — searches are built from your profile keywords, not a generic string
- **Parallel search** — 4 Nia queries run concurrently for speed
- **Dead link filter** — skips expired job pages before scoring
- **H1B hard filter** — applied before ranking, not after
- **Live progress** — every step shows in real time with timing

## How to use

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Add your API keys to .env
NIA_API_KEY=...
GITHUB_TOKEN=...   # optional but recommended

# 3. Run
streamlit run app.py
```

Upload your **resume PDF**, **LinkedIn export PDF** (Settings → Data Privacy → Get a copy of your data), and optionally your GitHub URL. Enter the role you want and hit **Find My Jobs**.

## Built for

OpenClaw Hackathon — Eragon × Nozomio × AgentMail
