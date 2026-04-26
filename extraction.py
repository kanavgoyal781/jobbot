import os
import requests
from pathlib import Path
from pypdf import PdfReader

CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs",
    ".java", ".cpp", ".c", ".rb", ".swift", ".kt", ".cs", ".sh",
}


def _extract_text(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        reader = PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    return path.read_text(encoding="utf-8")


def _github_headers() -> dict:
    token = os.getenv("GITHUB_TOKEN", "").strip()
    base = {"Accept": "application/vnd.github+json"}
    if token:
        base["Authorization"] = f"Bearer {token}"
    return base


def _fetch_github_deep(username: str, logger) -> tuple[list[str], str]:
    """Fetches README + code files from top repos. Returns (repo_names, combined_text)."""
    repo_names: list[str] = []
    all_sections: list[str] = []
    headers = _github_headers()

    try:
        resp = requests.get(
            f"https://api.github.com/users/{username}/repos",
            headers=headers,
            params={"per_page": 10, "sort": "updated"},
            timeout=10,
        )
        if resp.status_code == 403:
            remaining = resp.headers.get("X-RateLimit-Remaining", "?")
            logger.step("github_repos_list", "failed", f"Rate limited (remaining={remaining}). Set GITHUB_TOKEN in .env to fix.")
            return [], ""
        if resp.status_code != 200:
            logger.step("github_repos_list", "failed", f"GitHub API {resp.status_code} for user '{username}'")
            return [], ""

        repos = resp.json()
        if not repos:
            logger.step("github_repos_list", "skipped", f"No public repos found for '{username}'")
            return [], ""

        repos = sorted(repos, key=lambda r: r.get("stargazers_count", 0), reverse=True)[:5]
        logger.step("github_repos_list", "ok", f"Found {len(repos)} repos: {[r['name'] for r in repos]}")

        for repo in repos:
            repo_name = repo["name"]
            full_name = repo["full_name"]
            stars = repo.get("stargazers_count", 0)
            language = repo.get("language") or "unknown"
            repo_parts = [f"=== REPO: {full_name} | Stars: {stars} | Language: {language} ==="]

            try:
                readme_resp = requests.get(
                    f"https://api.github.com/repos/{full_name}/readme",
                    headers={**headers, "Accept": "application/vnd.github.raw"},
                    timeout=10,
                )
                if readme_resp.status_code == 200:
                    repo_parts.append(f"--- README ---\n{readme_resp.text[:5000]}")
            except Exception as e:
                logger.step(f"github_{repo_name}_readme", "failed", str(e))

            try:
                tree_resp = requests.get(
                    f"https://api.github.com/repos/{full_name}/git/trees/HEAD",
                    headers=headers,
                    params={"recursive": "1"},
                    timeout=15,
                )
                if tree_resp.status_code == 200:
                    tree = tree_resp.json().get("tree", [])
                    code_files = [
                        f for f in tree
                        if f.get("type") == "blob"
                        and Path(f["path"]).suffix.lower() in CODE_EXTENSIONS
                        and f.get("size", 999999) < 60000
                        and not any(skip in f["path"] for skip in [
                            "node_modules", ".min.", "dist/", "build/", "__pycache__", ".lock"
                        ])
                    ]
                    code_files.sort(key=lambda f: (len(f["path"].split("/")), f.get("size", 0)))
                    code_files = code_files[:12]

                    for file_info in code_files:
                        try:
                            raw_url = f"https://raw.githubusercontent.com/{full_name}/HEAD/{file_info['path']}"
                            file_resp = requests.get(raw_url, headers=headers, timeout=10)
                            if file_resp.status_code == 200:
                                repo_parts.append(f"--- {file_info['path']} ---\n{file_resp.text[:4000]}")
                        except Exception:
                            pass
            except Exception as e:
                logger.step(f"github_{repo_name}_tree", "failed", str(e))

            if len(repo_parts) > 1:
                all_sections.append("\n\n".join(repo_parts))
                repo_names.append(repo_name)
                logger.step(f"github_{repo_name}", "ok", f"Indexed {len(repo_parts)-1} sections")
            else:
                logger.step(f"github_{repo_name}", "skipped", "No content found")

    except Exception as e:
        logger.step("github_fetch", "failed", str(e))

    return repo_names, "\n\n".join(all_sections)
