"""Deploy generated HTML to GitHub Pages repository."""

from __future__ import annotations

import logging
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.config import DeploymentConfig

LOGGER = logging.getLogger(__name__)


def _run_git(
    args: list[str], cwd: Path, *, check: bool = True
) -> subprocess.CompletedProcess[str]:
    """Run a git command in the given directory."""
    cmd = ["git"] + args
    LOGGER.debug("Running: %s (cwd=%s)", " ".join(cmd), cwd)
    return subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, check=check, timeout=120
    )


def _ensure_clone(
    repo_url: str,
    branch: str,
    clone_path: Path,
    user_name: str,
    user_email: str,
) -> None:
    """Clone the repo if not present; pull latest if already cloned."""
    if (clone_path / ".git").is_dir():
        _run_git(["fetch", "origin"], cwd=clone_path)
        _run_git(["reset", "--hard", f"origin/{branch}"], cwd=clone_path)
        LOGGER.info("Pulled latest from %s", repo_url)
    else:
        clone_path.parent.mkdir(parents=True, exist_ok=True)
        _run_git(
            ["clone", "--branch", branch, "--single-branch", repo_url, str(clone_path)],
            cwd=clone_path.parent,
        )
        LOGGER.info("Cloned %s into %s", repo_url, clone_path)

    _run_git(["config", "user.name", user_name], cwd=clone_path)
    _run_git(["config", "user.email", user_email], cwd=clone_path)


def deploy_to_github_pages(
    html_source_path: str, deployment_config: DeploymentConfig | None
) -> None:
    """Copy generated HTML to the GitHub Pages repo, commit, and push.

    All errors are caught and logged so the main pipeline is never interrupted.
    """
    if not deployment_config or not deployment_config.enabled:
        LOGGER.debug("Deployment is disabled, skipping.")
        return

    clone_path = Path(deployment_config.local_clone_path).resolve()
    source = Path(html_source_path)

    if not source.is_file():
        LOGGER.error("HTML file not found for deployment: %s", source)
        return

    try:
        _ensure_clone(
            deployment_config.repo_url,
            deployment_config.branch,
            clone_path,
            deployment_config.git_user_name,
            deployment_config.git_user_email,
        )

        dest = clone_path / "index.html"
        shutil.copy2(str(source), str(dest))

        status = _run_git(["status", "--porcelain"], cwd=clone_path)
        if not status.stdout.strip():
            LOGGER.info("No changes to deploy.")
            return

        _run_git(["add", "index.html"], cwd=clone_path)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        message = deployment_config.commit_message.replace("{timestamp}", timestamp)
        _run_git(["commit", "-m", message], cwd=clone_path)
        _run_git(["push", "origin", deployment_config.branch], cwd=clone_path)
        LOGGER.info("Deployed to GitHub Pages successfully.")

    except subprocess.CalledProcessError as exc:
        LOGGER.error(
            "Git command failed during deployment: %s\nstdout: %s\nstderr: %s",
            exc.cmd,
            exc.stdout,
            exc.stderr,
        )
    except Exception:
        LOGGER.exception("Unexpected error during deployment.")
