"""Minimal GitHub REST client. Uses GITHUB_TOKEN (Actions) or `gh auth token` locally."""
from __future__ import annotations

import os
import subprocess
from typing import Any

import httpx

API = "https://api.github.com"


class GitHub:
    def __init__(self, repo: str | None = None, token: str | None = None):
        self.repo = repo or os.environ.get("GITHUB_REPOSITORY") or _repo_from_git()
        self.token = token or os.environ.get("GITHUB_TOKEN") or _gh_token()
        if not self.repo:
            raise RuntimeError("GitHub repo unknown: set GITHUB_REPOSITORY or add an origin remote")
        if not self.token:
            raise RuntimeError("GitHub token missing: set GITHUB_TOKEN or run `gh auth login`")
        self.c = httpx.Client(
            base_url=API, timeout=30.0,
            headers={"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "paper-radar"},
        )

    def _req(self, method: str, path: str, **kw: Any) -> Any:
        r = self.c.request(method, path, **kw)
        r.raise_for_status()
        return r.json() if r.content else None

    def list_issues(self, state: str = "open", labels: str | None = None, since: str | None = None) -> list[dict]:
        params: dict[str, Any] = {"state": state, "per_page": 100, "sort": "created", "direction": "asc"}
        if labels:
            params["labels"] = labels
        if since:
            params["since"] = since
        out, page = [], 1
        while True:
            params["page"] = page
            batch = self._req("GET", f"/repos/{self.repo}/issues", params=params) or []
            out.extend(i for i in batch if "pull_request" not in i)
            if len(batch) < 100:
                return out
            page += 1

    def issue_comments(self, number: int, since: str | None = None) -> list[dict]:
        params: dict[str, Any] = {"per_page": 100}
        if since:
            params["since"] = since
        return self._req("GET", f"/repos/{self.repo}/issues/{number}/comments", params=params) or []

    def create_issue(self, title: str, body: str, labels: list[str] | None = None) -> dict:
        return self._req("POST", f"/repos/{self.repo}/issues", json={"title": title, "body": body, "labels": labels or []})

    def comment(self, number: int, body: str) -> dict:
        return self._req("POST", f"/repos/{self.repo}/issues/{number}/comments", json={"body": body})

    def close(self, number: int, labels: list[str] | None = None) -> None:
        payload: dict[str, Any] = {"state": "closed", "state_reason": "completed"}
        if labels:
            payload["labels"] = labels
        self._req("PATCH", f"/repos/{self.repo}/issues/{number}", json=payload)

    def add_labels(self, number: int, labels: list[str]) -> None:
        self._req("POST", f"/repos/{self.repo}/issues/{number}/labels", json={"labels": labels})

    def ensure_label(self, name: str, color: str, description: str = "") -> None:
        r = self.c.get(f"/repos/{self.repo}/labels/{name}")
        if r.status_code == 404:
            self._req("POST", f"/repos/{self.repo}/labels", json={"name": name, "color": color, "description": description})


def _gh_token() -> str | None:
    try:
        out = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, encoding="utf-8", timeout=10)
        return out.stdout.strip() or None
    except Exception:
        return None


def _repo_from_git() -> str | None:
    try:
        url = subprocess.run(["git", "remote", "get-url", "origin"], capture_output=True, text=True, encoding="utf-8", timeout=5).stdout.strip()
    except Exception:
        return None
    if not url:
        return None
    url = url.removesuffix(".git")
    if ":" in url and "github.com" in url:
        return url.split("github.com", 1)[1].lstrip(":/")
    return None
