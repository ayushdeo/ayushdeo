import datetime
import hashlib
import os
import time
from pathlib import Path
from typing import Dict, List, Optional

import requests
from dateutil import relativedelta
from lxml import etree

# GitHub Actions should provide these secrets / env vars:
# - ACCESS_TOKEN: GitHub token with fine-grained read access
# - USER_NAME: your GitHub username
HEADERS = {"authorization": "token " + os.environ["ACCESS_TOKEN"]}
USER_NAME = os.environ["USER_NAME"]

# Optional: set your birthday here for the age counter.
# If you do not want an age counter, you can remove daily_readme() usage below
# and the matching SVG fields.
BIRTHDAY = datetime.datetime(2003, 8, 4)

QUERY_COUNT = {
    "user_getter": 0,
    "follower_getter": 0,
    "graph_repos_stars": 0,
    "recursive_loc": 0,
    "graph_commits": 0,
    "loc_query": 0,
}

ROOT = Path(__file__).resolve().parent
CACHE_DIR = ROOT / "cache"
CACHE_DIR.mkdir(exist_ok=True)


def daily_readme(birthday: datetime.datetime) -> str:
    """
    Returns the length of time since the birthday.
    Example: 'XX years, XX months, XX days'
    """
    diff = relativedelta.relativedelta(datetime.datetime.today(), birthday)
    return "{} {}, {} {}, {} {}{}".format(
        diff.years,
        "year" + format_plural(diff.years),
        diff.months,
        "month" + format_plural(diff.months),
        diff.days,
        "day" + format_plural(diff.days),
        " 🎂" if (diff.months == 0 and diff.days == 0) else "",
    )


def format_plural(unit: int) -> str:
    """
    Returns a properly formatted plural suffix.
    """
    return "s" if unit != 1 else ""


def simple_request(func_name: str, query: str, variables: Dict) -> requests.Response:
    """
    Returns a request, or raises an Exception if the response does not succeed.
    """
    request = requests.post(
        "https://api.github.com/graphql",
        json={"query": query, "variables": variables},
        headers=HEADERS,
        timeout=30,
    )
    if request.status_code == 200:
        return request
    raise Exception(func_name, " has failed with a", request.status_code, request.text, QUERY_COUNT)


def query_count(funct_id: str) -> None:
    """Counts how many times the GitHub GraphQL API is called."""
    global QUERY_COUNT
    QUERY_COUNT[funct_id] += 1


def graph_commits(start_date: str, end_date: str) -> int:
    """
    Uses GitHub's GraphQL v4 API to return total commit count.
    """
    query_count("graph_commits")
    query = """
    query($start_date: DateTime!, $end_date: DateTime!, $login: String!) {
        user(login: $login) {
            contributionsCollection(from: $start_date, to: $end_date) {
                contributionCalendar {
                    totalContributions
                }
            }
        }
    }"""
    variables = {"start_date": start_date, "end_date": end_date, "login": USER_NAME}
    request = simple_request(graph_commits.__name__, query, variables)
    return int(
        request.json()["data"]["user"]["contributionsCollection"]["contributionCalendar"]["totalContributions"]
    )


def stars_counter(data: List[Dict]) -> int:
    """Count total stars in repositories owned by me."""
    total_stars = 0
    for node in data:
        total_stars += node["node"]["stargazers"]["totalCount"]
    return total_stars


def graph_repos_stars(count_type: str, owner_affiliation: List[str], cursor: Optional[str] = None):
    """
    Uses GitHub's GraphQL v4 API to return total repository or star count.
    """
    query_count("graph_repos_stars")
    query = """
    query ($owner_affiliation: [RepositoryAffiliation], $login: String!, $cursor: String) {
        user(login: $login) {
            repositories(first: 100, after: $cursor, ownerAffiliations: $owner_affiliation) {
                totalCount
                edges {
                    node {
                        ... on Repository {
                            nameWithOwner
                            stargazers {
                                totalCount
                            }
                        }
                    }
                }
                pageInfo {
                    endCursor
                    hasNextPage
                }
            }
        }
    }"""
    variables = {"owner_affiliation": owner_affiliation, "login": USER_NAME, "cursor": cursor}
    request = simple_request(graph_repos_stars.__name__, query, variables)
    if count_type == "repos":
        return request.json()["data"]["user"]["repositories"]["totalCount"]
    if count_type == "stars":
        return stars_counter(request.json()["data"]["user"]["repositories"]["edges"])
    raise ValueError(f"Unknown count_type: {count_type}")


def recursive_loc(owner: str, repo_name: str, data: List[str], cache_comment: List[str], addition_total=0, deletion_total=0, my_commits=0, cursor: Optional[str] = None):
    """
    Uses GitHub's GraphQL v4 API and cursor pagination to fetch commits from a repository.
    """
    query_count("recursive_loc")
    query = """
    query ($repo_name: String!, $owner: String!, $cursor: String) {
        repository(name: $repo_name, owner: $owner) {
            defaultBranchRef {
                target {
                    ... on Commit {
                        history(first: 100, after: $cursor) {
                            totalCount
                            edges {
                                node {
                                    committedDate
                                    author {
                                        user {
                                            id
                                        }
                                    }
                                    deletions
                                    additions
                                }
                            }
                            pageInfo {
                                endCursor
                                hasNextPage
                            }
                        }
                    }
                }
            }
        }
    }"""
    variables = {"repo_name": repo_name, "owner": owner, "cursor": cursor}
    request = requests.post(
        "https://api.github.com/graphql",
        json={"query": query, "variables": variables},
        headers=HEADERS,
        timeout=30,
    )

    if request.status_code == 200:
        repo = request.json()["data"]["repository"]
        if repo["defaultBranchRef"] is not None:
            history = repo["defaultBranchRef"]["target"]["history"]
            return loc_counter_one_repo(
                owner,
                repo_name,
                data,
                cache_comment,
                history,
                addition_total,
                deletion_total,
                my_commits,
            )
        return 0, 0, 0

    force_close_file(data, cache_comment)
    if request.status_code == 403:
        raise Exception("Too many requests in a short amount of time! You've hit the non-documented anti-abuse limit!")
    raise Exception("recursive_loc() has failed with a", request.status_code, request.text, QUERY_COUNT)


def loc_counter_one_repo(owner: str, repo_name: str, data: list[str], cache_comment: list[str], history: dict, addition_total: int, deletion_total: int, my_commits: int):
    """
    Recursively call recursive_loc() only adding LOC value of commits authored by the current user.
    """
    for node in history["edges"]:
        author = node["node"].get("author", {})
        if author.get("user", {}) and author["user"].get("id") == OWNER_ID:
            my_commits += 1
            addition_total += node["node"]["additions"]
            deletion_total += node["node"]["deletions"]

    if history["edges"] == [] or not history["pageInfo"]["hasNextPage"]:
        return addition_total, deletion_total, my_commits
    return recursive_loc(
        owner,
        repo_name,
        data,
        cache_comment,
        addition_total,
        deletion_total,
        my_commits,
        history["pageInfo"]["endCursor"],
    )


def loc_query(owner_affiliation: List[str], comment_size: int = 0, force_cache: bool = False, cursor: Optional[str] = None, edges: Optional[List] = None):
    """
    Query all repositories I have access to and return the total LOC tuple.
    Returns [added_loc, deleted_loc, total_loc, cached]
    """
    if edges is None:
        edges = []

    query_count("loc_query")
    query = """
    query ($owner_affiliation: [RepositoryAffiliation], $login: String!, $cursor: String) {
        user(login: $login) {
            repositories(first: 60, after: $cursor, ownerAffiliations: $owner_affiliation) {
                edges {
                    node {
                        ... on Repository {
                            nameWithOwner
                            defaultBranchRef {
                                target {
                                    ... on Commit {
                                        history {
                                            totalCount
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
                pageInfo {
                    endCursor
                    hasNextPage
                }
            }
        }
    }"""
    variables = {"owner_affiliation": owner_affiliation, "login": USER_NAME, "cursor": cursor}
    request = simple_request(loc_query.__name__, query, variables)
    repos = request.json()["data"]["user"]["repositories"]
    if repos["pageInfo"]["hasNextPage"]:
        edges += repos["edges"]
        return loc_query(owner_affiliation, comment_size, force_cache, repos["pageInfo"]["endCursor"], edges)
    return cache_builder(edges + repos["edges"], comment_size, force_cache)


def cache_builder(edges: List, comment_size: int, force_cache: bool, loc_add=0, loc_del=0):
    """
    Checks each repository in edges to see if it has been updated since last cache.
    If it has, run recursive_loc on that repository to update LOC counts.
    """
    cached = True
    filename = CACHE_DIR / f"{hashlib.sha256(USER_NAME.encode('utf-8')).hexdigest()}.txt"
    try:
        with open(filename, "r", encoding="utf-8") as f:
            data = f.readlines()
    except FileNotFoundError:
        data = []
        if comment_size > 0:
            for _ in range(comment_size):
                data.append("This line is a comment block. Write whatever you want here.\n")
        with open(filename, "w", encoding="utf-8") as f:
            f.writelines(data)

    if len(data) - comment_size != len(edges) or force_cache:
        cached = False
        flush_cache(edges, filename, comment_size)
        with open(filename, "r", encoding="utf-8") as f:
            data = f.readlines()

    cache_comment = data[:comment_size]
    data = data[comment_size:]

    for index in range(len(edges)):
        repo_hash, commit_count, *__ = data[index].split()
        if repo_hash == hashlib.sha256(edges[index]["node"]["nameWithOwner"].encode("utf-8")).hexdigest():
            try:
                history = edges[index]["node"]["defaultBranchRef"]["target"]["history"]
                if int(commit_count) != history["totalCount"]:
                    owner, repo_name = edges[index]["node"]["nameWithOwner"].split("/")
                    loc = recursive_loc(owner, repo_name, data, cache_comment)
                    data[index] = (
                        repo_hash
                        + " "
                        + str(history["totalCount"])
                        + " "
                        + str(loc[2])
                        + " "
                        + str(loc[0])
                        + " "
                        + str(loc[1])
                        + "\n"
                    )
            except TypeError:
                data[index] = repo_hash + " 0 0 0 0\n"

    with open(filename, "w", encoding="utf-8") as f:
        f.writelines(cache_comment)
        f.writelines(data)

    for line in data:
        loc = line.split()
        loc_add += int(loc[3])
        loc_del += int(loc[4])
    return [loc_add, loc_del, loc_add - loc_del, cached]


def flush_cache(edges: List, filename: Path, comment_size: int) -> None:
    """Wipes the cache file."""
    with open(filename, "r", encoding="utf-8") as f:
        data = []
        if comment_size > 0:
            data = f.readlines()[:comment_size]
    with open(filename, "w", encoding="utf-8") as f:
        f.writelines(data)
        for node in edges:
            f.write(hashlib.sha256(node["node"]["nameWithOwner"].encode("utf-8")).hexdigest() + " 0 0 0 0\n")


def force_close_file(data: List[str], cache_comment: List[str]) -> None:
    """
    Forces the file to close, preserving whatever data was written to it.
    """
    filename = CACHE_DIR / f"{hashlib.sha256(USER_NAME.encode('utf-8')).hexdigest()}.txt"
    with open(filename, "w", encoding="utf-8") as f:
        f.writelines(cache_comment)
        f.writelines(data)
    print(
        "There was an error while writing to the cache file. The file,",
        filename,
        "has had the partial data saved and closed.",
    )


def commit_counter(comment_size: int) -> int:
    """Counts up total commits, using the cache file created by cache_builder."""
    total_commits = 0
    filename = CACHE_DIR / f"{hashlib.sha256(USER_NAME.encode('utf-8')).hexdigest()}.txt"
    with open(filename, "r", encoding="utf-8") as f:
        data = f.readlines()
    _cache_comment = data[:comment_size]
    data = data[comment_size:]
    for line in data:
        total_commits += int(line.split()[2])
    return total_commits


def user_getter(username: str):
    """Returns the account ID and creation time of the user."""
    query_count("user_getter")
    query = """
    query($login: String!) {
        user(login: $login) {
            id
            createdAt
        }
    }"""
    variables = {"login": username}
    request = simple_request(user_getter.__name__, query, variables)
    return {"id": request.json()["data"]["user"]["id"]}, request.json()["data"]["user"]["createdAt"]


def follower_getter(username: str) -> int:
    """Returns the number of followers of the user."""
    query_count("follower_getter")
    query = """
    query($login: String!) {
        user(login: $login) {
            followers {
                totalCount
            }
        }
    }"""
    request = simple_request(follower_getter.__name__, query, {"login": username})
    return int(request.json()["data"]["user"]["followers"]["totalCount"])


def svg_overwrite(filename: str, age_data: str, commit_data: int, star_data: int, repo_data: int, contrib_data: int, follower_data: int, loc_data: List[str]):
    """
    Parse SVG files and update elements with age, commits, stars, repositories, followers, and LOC.
    """
    tree = etree.parse(str(ROOT / filename))
    root = tree.getroot()
    justify_format(root, "commit_data", commit_data, 22)
    justify_format(root, "star_data", star_data, 14)
    justify_format(root, "repo_data", repo_data, 6)
    justify_format(root, "contrib_data", contrib_data)
    justify_format(root, "follower_data", follower_data, 10)
    justify_format(root, "loc_data", loc_data[2], 9)
    justify_format(root, "loc_add", loc_data[0])
    justify_format(root, "loc_del", loc_data[1], 7)
    # Optional age field if present in your SVGs:
    justify_format(root, "age_data", age_data)
    tree.write(str(ROOT / filename), encoding="utf-8", xml_declaration=True)


def justify_format(root, element_id: str, new_text, length: int = 0):
    """
    Updates and formats the text of the element, and modifies the amount of dots in the previous element.
    """
    if isinstance(new_text, int):
        new_text = f"{'{:,}'.format(new_text)}"
    new_text = str(new_text)
    find_and_replace(root, element_id, new_text)
    just_len = max(0, length - len(new_text))
    if just_len <= 2:
        dot_map = {0: "", 1: " ", 2: ". "}
        dot_string = dot_map[just_len]
    else:
        dot_string = " " + ("." * just_len) + " "
    find_and_replace(root, f"{element_id}_dots", dot_string)


def find_and_replace(root, element_id: str, new_text: str):
    """Finds the element in the SVG file and replaces its text with a new value."""
    element = root.find(f".//*[@id='{element_id}']")
    if element is not None:
        element.text = new_text


def formatter(query_type: str, difference: float, funct_return=False, whitespace: int = 0):
    """
    Prints a formatted time differential.
    Returns formatted result if whitespace is specified, otherwise returns raw result.
    """
    print("{:<23}".format("   " + query_type + ":"), sep="", end="")
    if difference > 1:
        print("{:>12}".format("%.4f" % difference + " s "))
    else:
        print("{:>12}".format("%.4f" % (difference * 1000) + " ms"))
    if whitespace:
        return f"{'{:,}'.format(funct_return): <{whitespace}}"
    return funct_return


def perf_counter(funct, *args):
    """Calculates the time it takes for a function to run."""
    start = time.perf_counter()
    funct_return = funct(*args)
    return funct_return, time.perf_counter() - start


if __name__ == "__main__":
    print("Calculation times:")

    user_data, user_time = perf_counter(user_getter, USER_NAME)
    OWNER_ID, acc_date = user_data
    formatter("account data", user_time)

    age_data, age_time = perf_counter(daily_readme, BIRTHDAY)
    formatter("age calculation", age_time)

    total_loc, loc_time = perf_counter(loc_query, ["OWNER", "COLLABORATOR", "ORGANIZATION_MEMBER"], 7)
    formatter("LOC (cached)", loc_time) if total_loc[-1] else formatter("LOC (no cache)", loc_time)

    commit_data, commit_time = perf_counter(commit_counter, 7)
    star_data, star_time = perf_counter(graph_repos_stars, "stars", ["OWNER"])
    repo_data, repo_time = perf_counter(graph_repos_stars, "repos", ["OWNER"])
    contrib_data, contrib_time = perf_counter(graph_repos_stars, "repos", ["OWNER", "COLLABORATOR", "ORGANIZATION_MEMBER"])
    follower_data, follower_time = perf_counter(follower_getter, USER_NAME)

    for index in range(len(total_loc) - 1):
        total_loc[index] = "{:,}".format(total_loc[index])

    svg_overwrite("dark_mode.svg", age_data, commit_data, star_data, repo_data, contrib_data, follower_data, total_loc[:-1])
    svg_overwrite("light_mode.svg", age_data, commit_data, star_data, repo_data, contrib_data, follower_data, total_loc[:-1])

    total_time = user_time + age_time + loc_time + commit_time + star_time + repo_time + contrib_time + follower_time
    print(
        "\033[F\033[F\033[F\033[F\033[F\033[F\033[F\033[F",
        "{:<21}".format("Total function time:"),
        "{:>11}".format("%.4f" % total_time + " s "),
        "\033[E\033[E\033[E\033[E\033[E\033[E\033[E\033[E",
        sep="",
    )

    print("Total GitHub GraphQL API calls:", "{:>3}".format(sum(QUERY_COUNT.values())))
    for funct_name, count in QUERY_COUNT.items():
        print("{:<28}".format("   " + funct_name + ":"), "{:>6}".format(count))
