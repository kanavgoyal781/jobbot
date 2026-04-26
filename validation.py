import re
from pathlib import Path
from pydantic import BaseModel, Field, field_validator, model_validator

from extraction import _extract_text

RESUME_SECTIONS = ["experience", "work experience", "education", "projects"]
LINKEDIN_SECTIONS = ["experience", "education"]


class ResumeUploadInput(BaseModel):
    file_path: str = Field(..., description="Path to resume PDF or TXT")

    @field_validator("file_path")
    @classmethod
    def validate_resume(cls, v: str) -> str:
        path = Path(v)
        if not path.exists():
            raise ValueError(f"Resume file not found: {v}")
        if path.suffix.lower() not in [".pdf", ".txt"]:
            raise ValueError("Resume must be .pdf or .txt")
        text = _extract_text(path)
        lower = text.lower()
        found = [s for s in RESUME_SECTIONS if s in lower]
        if len(found) < 2:
            raise ValueError(
                f"Resume must contain at least 2 sections (Experience, Education, Projects). "
                f"Found: {found if found else 'none'}. Please upload a real resume PDF."
            )
        return str(path.absolute())


class LinkedInUploadInput(BaseModel):
    file_path: str = Field(..., description="Path to LinkedIn PDF export")

    @field_validator("file_path")
    @classmethod
    def validate_linkedin(cls, v: str) -> str:
        path = Path(v)
        if not path.exists():
            raise ValueError(f"LinkedIn file not found: {v}")
        if path.suffix.lower() != ".pdf":
            raise ValueError("LinkedIn profile must be a PDF")
        text = _extract_text(path)
        lower = text.lower()
        if not any(s in lower for s in LINKEDIN_SECTIONS):
            raise ValueError(
                "LinkedIn PDF must contain 'Experience' or 'Education'. "
                "Please export your full LinkedIn profile (Settings → Data Privacy → Get a copy of your data)."
            )
        return str(path.absolute())


class GitHubInput(BaseModel):
    profile_url: str = Field(..., description="GitHub profile URL or username")
    username: str = Field(default="")

    @model_validator(mode="after")
    def parse_username(self) -> "GitHubInput":
        raw = self.profile_url.strip().rstrip("/")
        if "github.com/" in raw:
            username = raw.split("github.com/")[-1].split("/")[0]
        elif re.match(r"^[a-zA-Z0-9][a-zA-Z0-9\-]{0,38}$", raw):
            username = raw
        else:
            raise ValueError(
                f"Invalid GitHub URL or username: '{raw}'. "
                "Use https://github.com/username or just the username."
            )
        if not username:
            raise ValueError("Could not parse GitHub username.")
        self.username = username
        return self
