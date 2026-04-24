#!/usr/bin/env python3
"""
Monthly README updater for AparneetDey's GitHub profile.

Fetches all public repositories, scores and filters them, then regenerates
the Featured Projects section in README.md between the <!-- PROJECTS:START -->
and <!-- PROJECTS:END --> markers.

After updating the README it opens a GitHub Issue to notify the owner.
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib import request, error as urllib_error

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).parent
REPO_ROOT = SCRIPT_DIR.parent.parent
README_PATH = REPO_ROOT / "README.md"
CONFIG_PATH = SCRIPT_DIR.parent / "projects_config.json"

GITHUB_API = "https://api.github.com"
OWNER = os.environ.get("GITHUB_REPOSITORY_OWNER", "AparneetDey")
TOKEN = os.environ.get("GITHUB_TOKEN", "")

SECTION_START = "<!-- PROJECTS:START -->"
SECTION_END = "<!-- PROJECTS:END -->"

# Language → readable label
LANG_LABELS = {
    "javascript": "JavaScript",
    "typescript": "TypeScript",
    "python": "Python",
    "java": "Java",
    "gdscript": "GDScript",
    "css": "CSS",
    "html": "HTML",
    "c++": "C++",
    "c": "C",
}

# Category detection by primary language
LANG_TO_CATEGORY = {
    "gdscript": "gamedev",
    "java": "java",
}

# Recent-activity thresholds (in days)
RECENT_3M = 90
RECENT_6M = 180


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def api_get(path: str) -> dict | list:
    """Make an authenticated GET request to the GitHub API."""
    url = f"{GITHUB_API}{path}"
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    req = request.Request(url, headers=headers)
    with request.urlopen(req) as resp:
        return json.loads(resp.read())


def api_post(path: str, payload: dict) -> dict:
    """Make an authenticated POST request to the GitHub API."""
    url = f"{GITHUB_API}{path}"
    data = json.dumps(payload).encode()
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
    }
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    req = request.Request(url, data=data, headers=headers, method="POST")
    with request.urlopen(req) as resp:
        return json.loads(resp.read())


def days_since(iso_date: str) -> int:
    """Return days elapsed since an ISO-8601 date string."""
    dt = datetime.fromisoformat(iso_date.replace("Z", "+00:00"))
    return (datetime.now(timezone.utc) - dt).days


def is_excluded(name: str, patterns: list[str]) -> bool:
    """Return True if the repo name matches any exclusion pattern."""
    n = name.lower()
    return any(p.lower() in n for p in patterns)


def score_repo(repo: dict, overrides: dict) -> int:
    """Compute a numeric score for a repository."""
    name = repo["name"]
    if name in overrides and "priority" in overrides[name]:
        return overrides[name]["priority"]

    score = 0
    score += repo.get("stargazers_count", 0) * 10

    updated = repo.get("updated_at", "")
    if updated:
        age = days_since(updated)
        if age <= RECENT_3M:
            score += 15
        elif age <= RECENT_6M:
            score += 8

    if repo.get("description"):
        score += 5
    if repo.get("topics"):
        score += 3

    # Penalise very simple static-only projects
    lang = (repo.get("language") or "").lower()
    if lang in ("css", "html"):
        score -= 5

    return score


def detect_category(repo: dict, overrides: dict) -> str:
    """Return a category string for the repo."""
    name = repo["name"]
    if name in overrides and "category" in overrides[name]:
        return overrides[name]["category"]
    lang = (repo.get("language") or "").lower()
    return LANG_TO_CATEGORY.get(lang, "fullstack")


def get_tech_badges(tech_list: list[str]) -> str:
    """Return a backtick-separated tech tag string."""
    return " ".join(f"`{t}`" for t in tech_list)


def build_project_entry(repo: dict, overrides: dict) -> str:
    """Build a markdown block for a single project."""
    name = repo["name"]
    cfg = overrides.get(name, {})

    display_name = cfg.get("display_name", name.replace("-", " "))
    description = cfg.get("description") or repo.get("description") or "No description yet."
    icon = cfg.get("icon", "🔗")
    tech_list = cfg.get("tech") or []
    repo_url = repo["html_url"]

    # Freshness indicator
    updated = repo.get("updated_at", "")
    freshness = ""
    if updated and days_since(updated) <= RECENT_3M:
        freshness = " `🆕 Active`"

    lines = [
        f"### {icon} [{display_name}]({repo_url}){freshness}",
        f"{description}",
        "",
    ]
    if tech_list:
        lines.append(get_tech_badges(tech_list))
    lines.append("")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def build_projects_section(repos: list[dict], config: dict) -> str:
    """Build the full Projects section markdown."""
    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%-d %B %Y")

    overrides = config.get("overrides", {})
    exclude_patterns = config.get("exclude_patterns", [])
    max_projects = config.get("max_projects", 6)

    # Filter
    candidates = [
        r for r in repos
        if not r.get("fork")
        and not r.get("archived")
        and not is_excluded(r["name"], exclude_patterns)
        and r["name"] != OWNER
    ]

    # Score and sort
    candidates.sort(key=lambda r: score_repo(r, overrides), reverse=True)
    selected = candidates[:max_projects]

    # Sort selected: game dev first, then by score
    def sort_key(r):
        cat = detect_category(r, overrides)
        cat_order = {"gamedev": 0, "fullstack": 1, "java": 2, "frontend": 3}
        return (cat_order.get(cat, 9), -score_repo(r, overrides))

    selected.sort(key=sort_key)

    lines = [f"*Auto-updated: {timestamp}*", ""]
    for repo in selected:
        lines.append(build_project_entry(repo, overrides))

    return "\n".join(lines)


def update_readme(new_section: str) -> tuple[bool, str, str]:
    """
    Replace the content between PROJECTS:START and PROJECTS:END markers.
    Returns (changed, old_section, new_section).
    """
    content = README_PATH.read_text(encoding="utf-8")

    pattern = re.compile(
        rf"{re.escape(SECTION_START)}.*?{re.escape(SECTION_END)}",
        re.DOTALL,
    )
    replacement = f"{SECTION_START}\n{new_section}\n{SECTION_END}"

    match = pattern.search(content)
    old_section = match.group(0) if match else ""
    updated = pattern.sub(replacement, content)

    if updated == content:
        return False, old_section, ""

    README_PATH.write_text(updated, encoding="utf-8")
    return True, old_section, replacement


def create_notification_issue(added: list[str], removed: list[str], month_label: str) -> None:
    """Open a GitHub Issue summarising the monthly README update."""
    repo_slug = f"{OWNER}/{OWNER}"

    body_lines = [
        f"## 📋 Monthly README Update — {month_label}",
        "",
        "The Featured Projects section has been automatically refreshed.",
        "",
    ]
    if added:
        body_lines += ["**➕ Projects added / kept this month:**"]
        body_lines += [f"- {p}" for p in added]
        body_lines += [""]
    if removed:
        body_lines += ["**➖ Projects removed this month:**"]
        body_lines += [f"- {p}" for p in removed]
        body_lines += [""]
    body_lines += [
        "---",
        "_To manually adjust which projects appear, edit [`.github/projects_config.json`]"
        f"(https://github.com/{repo_slug}/blob/main/.github/projects_config.json)._",
    ]

    payload = {
        "title": f"📝 README auto-updated — {month_label}",
        "body": "\n".join(body_lines),
        "labels": ["readme-update"],
    }
    try:
        api_post(f"/repos/{repo_slug}/issues", payload)
        print("✅ Notification issue created.")
    except urllib_error.HTTPError as exc:
        # Label might not exist — retry without labels
        if exc.code == 422:
            payload.pop("labels")
            api_post(f"/repos/{repo_slug}/issues", payload)
            print("✅ Notification issue created (without label).")
        else:
            raise


def extract_project_names(section: str) -> set[str]:
    """Extract project display names from a projects section string."""
    return set(re.findall(r"### .+? \[(.+?)\]", section))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    print(f"Fetching repositories for {OWNER} …")
    try:
        repos = api_get(f"/users/{OWNER}/repos?per_page=100&type=owner")
    except urllib_error.HTTPError as exc:
        print(f"❌ GitHub API error: {exc}", file=sys.stderr)
        return 1

    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    new_section = build_projects_section(repos, config)

    changed, old_section, _ = update_readme(new_section)

    if not changed:
        print("ℹ️  README already up-to-date — no changes committed.")
        return 0

    print("✅ README.md updated.")

    old_names = extract_project_names(old_section)
    new_names = extract_project_names(new_section)
    added = sorted(new_names - old_names)
    removed = sorted(old_names - new_names)

    month_label = datetime.now(timezone.utc).strftime("%B %Y")
    create_notification_issue(added, removed, month_label)

    return 0


if __name__ == "__main__":
    sys.exit(main())
