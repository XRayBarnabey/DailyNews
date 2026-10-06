import os
import subprocess
from pathlib import Path


def _git_revision() -> str:
    if revision := os.getenv("GIT_SHA", "").strip():
        return revision[:7]
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).resolve().parent,
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def get_version() -> str:
    release = (Path(__file__).with_name("VERSION").read_text(encoding="utf-8").strip()) or "dev"
    revision = _git_revision()
    return f"v{release} ({revision})" if revision else f"v{release}"


APP_VERSION = get_version()
