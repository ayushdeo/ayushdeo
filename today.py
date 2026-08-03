import os
import sys
from pathlib import Path
from typing import Dict

import requests
from lxml import etree

# GitHub Actions provides these:
#   ACCESS_TOKEN: a GitHub token with read access
#   USER_NAME:    your GitHub login
HEADERS = {"authorization": "token " + os.environ["ACCESS_TOKEN"]}
USER_NAME = os.environ["USER_NAME"]
ROOT = Path(__file__).resolve().parent

API = "https://api.github.com/graphql"


def run_query(query: str, variables: Dict) -> Dict:
    """Run a GraphQL query and return its `data`, raising on any error."""
    resp = requests.post(API, json={"query": query, "variables": variables}, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    if "errors" in payload:
        raise RuntimeError(payload["errors"])
    return payload["data"]


def fetch_stats() -> Dict[str, str]:
    """
    Fetch lightweight, always-available profile stats in a single query.

    These come straight from the user object (repos, stars, followers,
    contribution calendar, join date) so there is no per-commit crawling and
    therefore no risk of tripping GitHub's anti-abuse rate limit.
    """
    query = """
    query ($login: String!, $cursor: String) {
        user(login: $login) {
            createdAt
            followers { totalCount }
            contributionsCollection { totalContributions }
            repositories(first: 100, after: $cursor, ownerAffiliations: [OWNER]) {
                totalCount
                nodes { stargazerCount }
                pageInfo { hasNextPage endCursor }
            }
        }
    }"""

    repos = 0
    stars = 0
    cursor = None
    user = None
    while True:
        user = run_query(query, {"login": USER_NAME, "cursor": cursor})["user"]
        repo_page = user["repositories"]
        repos = repo_page["totalCount"]
        stars += sum(node["stargazerCount"] for node in repo_page["nodes"])
        if not repo_page["pageInfo"]["hasNextPage"]:
            break
        cursor = repo_page["pageInfo"]["endCursor"]

    return {
        "repo_data": str(repos),
        "star_data": str(stars),
        "follower_data": str(user["followers"]["totalCount"]),
        "contrib_data": str(user["contributionsCollection"]["totalContributions"]),
        "since_data": user["createdAt"][:4],
    }


def svg_overwrite(filename: str, stats: Dict[str, str]) -> None:
    """Replace the text of each stat element in the SVG by its id."""
    tree = etree.parse(str(ROOT / filename))
    root = tree.getroot()
    for element_id, value in stats.items():
        element = root.find(f".//*[@id='{element_id}']")
        if element is not None:
            element.text = value
    tree.write(str(ROOT / filename), encoding="utf-8", xml_declaration=True)


if __name__ == "__main__":
    try:
        stats = fetch_stats()
    except Exception as exc:  # never fail the build on a transient API hiccup
        print(f"Stat fetch failed; leaving profile.svg unchanged: {exc}", file=sys.stderr)
        sys.exit(0)
    svg_overwrite("profile.svg", stats)
    print("Updated profile.svg with:", stats)
