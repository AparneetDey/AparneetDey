#!/usr/bin/env python3
"""
Weekly README updater for AparneetDey's GitHub profile.

Fetches all owned repositories, scores and filters them, then regenerates
the Featured Projects section in README.md between the <!-- PROJECTS:START -->
and <!-- PROJECTS:END --> markers.

After updating the README it opens a GitHub Issue to notify the owner.
"""

import json
import math
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

# Category detection by primary language
LANG_TO_CATEGORY = {
    "gdscript": "gamedev",
    "java": "java",
}

PORTFOLIO_DIMENSIONS = {
    "technical_depth": 25,
    "development_effort": 20,
    "completeness_polish": 20,
    "engineering_quality": 15,
    "recent_activity": 10,
    "portfolio_value": 10,
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def api_get(path: str, include_headers: bool = False) -> dict | list | tuple[dict | list, dict]:
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
        data = json.loads(resp.read())
        if include_headers:
            return data, dict(resp.headers.items())
        return data


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


def clamp_score(value: int | float, max_score: int) -> int:
    """Clamp a score to an integer between 0 and max_score."""
    return max(0, min(max_score, int(round(value))))


def score_recent_activity(repo: dict) -> int:
    """Score recent meaningful activity with low portfolio weight."""
    updated = repo.get("pushed_at") or repo.get("updated_at")
    if not updated:
        return 0
    age_days = days_since(updated)
    if age_days <= 14:
        return 10
    if age_days <= 45:
        return 8
    if age_days <= 90:
        return 6
    if age_days <= 180:
        return 4
    if age_days <= 365:
        return 2
    return 0


def estimate_development_effort(repo: dict) -> int:
    """Estimate development effort from commit volume and project timespan."""
    commit_count = int(repo.get("_commit_count", 0) or 0)
    if commit_count <= 0:
        return 0

    commit_signal = min(12.0, math.log1p(commit_count) * 2.6)
    spread_signal = 0.0
    created_at = repo.get("created_at")
    updated_at = repo.get("pushed_at") or repo.get("updated_at")
    if created_at and updated_at:
        spread_days = max(0, days_since(created_at) - days_since(updated_at))
        spread_signal = min(8.0, spread_days / 45.0)

    iterative_bonus = 0.0
    if commit_count >= 120:
        iterative_bonus = 3.0
    elif commit_count >= 60:
        iterative_bonus = 2.0
    elif commit_count >= 25:
        iterative_bonus = 1.0

    return clamp_score(commit_signal + spread_signal + iterative_bonus, 20)


def detect_category(repo: dict, overrides: dict) -> str:
    """Return a category string for the repo."""
    name = repo["name"]
    if name in overrides and "category" in overrides[name]:
        return overrides[name]["category"]
    lang = (repo.get("language") or "").lower()
    return LANG_TO_CATEGORY.get(lang, "general")


def get_tech_badges(tech_list: list[str]) -> str:
    """Return a backtick-separated tech tag string."""
    return " ".join(f"`{t}`" for t in tech_list)


def infer_status(repo: dict, total_score: int) -> str:
    """Infer project status when not manually set."""
    updated = repo.get("pushed_at") or repo.get("updated_at")
    if updated and days_since(updated) <= 60 and total_score >= 65:
        return "ACTIVE"
    if total_score >= 65:
        return "COMPLETED"
    return "SUBSTANTIAL_UNFINISHED"


def evaluate_portfolio_dimensions(repo: dict, cfg: dict) -> dict[str, int]:
    """Evaluate or estimate all rubric dimensions."""
    configured = cfg.get("portfolio_scores", {})
    topics_count = len(repo.get("topics") or [])
    has_description = bool(repo.get("description"))
    has_homepage = bool(repo.get("homepage"))

    technical_depth = configured.get("technical_depth")
    if technical_depth is None:
        technical_depth = 6 + min(8, topics_count * 2) + (3 if has_description else 0)

    development_effort = configured.get("development_effort")
    if development_effort is None:
        development_effort = estimate_development_effort(repo)

    completeness_polish = configured.get("completeness_polish")
    if completeness_polish is None:
        completeness_polish = 6 + (4 if has_description else 0) + (2 if has_homepage else 0)

    engineering_quality = configured.get("engineering_quality")
    if engineering_quality is None:
        engineering_quality = 5 + min(6, topics_count)

    recent_activity = configured.get("recent_activity")
    if recent_activity is None:
        recent_activity = score_recent_activity(repo)

    portfolio_value = configured.get("portfolio_value")
    if portfolio_value is None:
        portfolio_value = 4 + (2 if has_description else 0) + min(4, topics_count)

    return {
        "technical_depth": clamp_score(technical_depth, PORTFOLIO_DIMENSIONS["technical_depth"]),
        "development_effort": clamp_score(development_effort, PORTFOLIO_DIMENSIONS["development_effort"]),
        "completeness_polish": clamp_score(completeness_polish, PORTFOLIO_DIMENSIONS["completeness_polish"]),
        "engineering_quality": clamp_score(engineering_quality, PORTFOLIO_DIMENSIONS["engineering_quality"]),
        "recent_activity": clamp_score(recent_activity, PORTFOLIO_DIMENSIONS["recent_activity"]),
        "portfolio_value": clamp_score(portfolio_value, PORTFOLIO_DIMENSIONS["portfolio_value"]),
    }


def score_repo(repo: dict, overrides: dict) -> int:
    """Compute total portfolio score (0-100) and attach metadata."""
    name = repo.get("name", "")
    cfg = overrides.get(name, {})
    scores = evaluate_portfolio_dimensions(repo, cfg)
    total = sum(scores.values())

    repo["_portfolio_scores"] = scores
    repo["_portfolio_total"] = total
    repo["_portfolio_status"] = cfg.get("status") or infer_status(repo, total)
    repo["_portfolio_category"] = detect_category(repo, overrides)
    return total


def get_rank_badges(repo: dict) -> str:
    """Build README badge from project status."""
    status = repo.get("_portfolio_status", "SUBSTANTIAL_UNFINISHED")
    icons = {
        "COMPLETED": "✅",
        "ACTIVE": "🆕",
        "SUBSTANTIAL_UNFINISHED": "🚧",
    }
    icon = icons.get(status, "🔗")
    return f" `{icon} {status}`"


def build_project_entry(repo: dict, overrides: dict) -> str:
    """Build a markdown block for a single project."""
    name = repo["name"]
    cfg = overrides.get(name, {})

    display_name = cfg.get("display_name", name.replace("-", " "))
    description = cfg.get("description") or repo.get("description") or "No description yet."
    icon = cfg.get("icon", "🔗")
    tech_list = cfg.get("tech") or []
    repo_url = repo["html_url"]
    status_badges = get_rank_badges(repo)

    lines = [
        f"### {icon} [{display_name}]({repo_url}){status_badges}",
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
    timestamp = f"{now.day} {now.strftime('%B %Y')}"

    overrides = config.get("overrides", {})
    exclude_patterns = config.get("exclude_patterns", [])
    max_projects = config.get("max_projects", 6)
    max_per_category = config.get("max_per_category", 2)
    showcase_min_score = config.get("showcase_min_score", 65)

    # Filter
    candidates = [
        r for r in repos
        if not r.get("fork")
        and not r.get("archived")
        and not r.get("private", False)
        and not is_excluded(r["name"], exclude_patterns)
        and r["name"] != OWNER
    ]

    # Score all eligible repos with portfolio rubric
    for repo in candidates:
        score_repo(repo, overrides)
    candidates.sort(key=lambda r: r.get("_portfolio_total", 0), reverse=True)

    # Select showcase-worthy projects with diversity by category
    selected: list[dict] = []
    category_counts: dict[str, int] = {}
    for repo in candidates:
        total = repo.get("_portfolio_total", 0)
        if total < showcase_min_score:
            continue
        category = repo.get("_portfolio_category", "general")
        if category_counts.get(category, 0) >= max_per_category:
            continue
        selected.append(repo)
        category_counts[category] = category_counts.get(category, 0) + 1
        if len(selected) >= max_projects:
            break

    # Fallback when strict showcase filter would produce an empty section
    if not selected:
        selected = candidates[:max_projects]

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


def create_notification_issue(added: list[str], removed: list[str], update_label: str) -> None:
    """Open a GitHub Issue summarising the weekly README update."""
    repo_slug = f"{OWNER}/{OWNER}"

    body_lines = [
        f"## 📋 Weekly README Update — {update_label}",
        "",
        "The Featured Projects section has been automatically refreshed.",
        "",
    ]
    if added:
        body_lines += ["**➕ Projects added / kept this week:**"]
        body_lines += [f"- {p}" for p in added]
        body_lines += [""]
    if removed:
        body_lines += ["**➖ Projects removed this week:**"]
        body_lines += [f"- {p}" for p in removed]
        body_lines += [""]
    body_lines += [
        "---",
        "_To manually adjust which projects appear, edit [`.github/projects_config.json`]"
        f"(https://github.com/{repo_slug}/blob/main/.github/projects_config.json)._",
    ]

    payload = {
        "title": f"📝 README auto-updated — {update_label}",
        "body": "\n".join(body_lines),
        "labels": ["readme-update"],
    }
    try:
        api_post(f"/repos/{repo_slug}/issues", payload)
        print("✅ Notification issue created.")
    except urllib_error.HTTPError as exc:
        # Label might not exist — retry without labels
        if exc.code == 422:
            print('⚠️  Label "readme-update" not found, retrying without labels...')
            payload.pop("labels")
            api_post(f"/repos/{repo_slug}/issues", payload)
            print("✅ Notification issue created (without label).")
        else:
            raise


def extract_project_names(section: str) -> set[str]:
    """Extract project display names from a projects section string."""
    return set(re.findall(r"### [^\n]+? \[([^\n]+?)\]", section))


def get_owned_repositories(owner: str) -> list[dict]:
    """Fetch every owned repository, handling pagination."""
    repos: list[dict] = []
    page = 1
    while True:
        if TOKEN:
            path = f"/user/repos?visibility=public&type=owner&sort=updated&per_page=100&page={page}"
        else:
            path = f"/users/{owner}/repos?type=owner&sort=updated&per_page=100&page={page}"
        batch = api_get(path)
        if not isinstance(batch, list):
            raise RuntimeError("Unexpected API response while fetching repositories.")
        if not batch:
            break
        repos.extend(batch)
        page += 1
    return repos


def get_commit_count(owner: str, repo_name: str) -> int:
    """Fetch total commits for default branch using Link pagination."""
    path = f"/repos/{owner}/{repo_name}/commits?per_page=1"
    try:
        data, headers = api_get(path, include_headers=True)
    except urllib_error.HTTPError as exc:
        if exc.code == 409:
            return 0
        raise

    if not isinstance(data, list) or not data:
        return 0

    link_header = headers.get("Link", "")
    match = re.search(r"[?&]page=(\d+)>;\s*rel=\"last\"", link_header)
    if match:
        return int(match.group(1))
    return len(data)


def attach_commit_counts(repos: list[dict], owner: str) -> None:
    """Attach commit counts to each repo for ranking."""
    for repo in repos:
        repo["_commit_count"] = get_commit_count(owner, repo["name"])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    print(f"Fetching repositories for {OWNER} …")
    try:
        repos = get_owned_repositories(OWNER)
    except urllib_error.HTTPError as exc:
        print(f"❌ GitHub API error: {exc}", file=sys.stderr)
        return 1

    if TOKEN:
        print("Fetching commit counts for repositories …")
        try:
            attach_commit_counts(repos, OWNER)
        except urllib_error.HTTPError as exc:
            print(f"❌ GitHub API error while fetching commit counts: {exc}", file=sys.stderr)
            return 1
    else:
        print("⚠️ No GITHUB_TOKEN found; skipping commit-count scoring.")

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

    update_label = datetime.now(timezone.utc).strftime("%d %B %Y")
    create_notification_issue(added, removed, update_label)

    return 0


if __name__ == "__main__":
    sys.exit(main())
