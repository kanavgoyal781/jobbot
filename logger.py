import os
import json
import uuid
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SessionLogger:
    def __init__(self):
        self.session_id = str(uuid.uuid4())[:8].upper()
        self._log: dict = {
            "session_id": self.session_id,
            "started_at": _now(),
            "status": "in_progress",
            "steps": [],
            "error": None,
            "finished_at": None,
        }
        os.makedirs("logs", exist_ok=True)

    def step(self, name: str, status: str, detail: str = "") -> dict:
        entry = {"step": name, "status": status, "detail": detail, "ts": _now()}
        self._log["steps"].append(entry)
        self._save()
        return entry

    def fail(self, reason: str) -> None:
        self._log["status"] = "failed"
        self._log["error"] = reason
        self._log["finished_at"] = _now()
        self._save()
        with open("logs/dead_letter.jsonl", "a") as f:
            f.write(json.dumps({
                "session_id": self.session_id,
                "ts": self._log["finished_at"],
                "reason": reason,
                "steps": self._log["steps"],
            }) + "\n")

    def success(self) -> None:
        self._log["status"] = "passed"
        self._log["finished_at"] = _now()
        self._save()

    def _save(self) -> None:
        with open(f"logs/{self.session_id}.json", "w") as f:
            json.dump(self._log, f, indent=2)

    def get_log(self) -> dict:
        return dict(self._log)
