import json
import time
from functools import wraps
from typing import Dict, Optional

from github import Github, GithubException
from pydantic import BaseModel
from ratelimit import limits, sleep_and_retry
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn

from anjin.config import settings

"""
You probably shouldn't run this script.  It is very slow because of Github's rate limits.
This script populates a JSON file with information about the changelogs of popular Python packages.
It uses the GitHub API to search for repositories, check for changelog files or release notes,
and then saves the information to a JSON file.
"""


console = Console()


class PackageInfo(BaseModel):
    name: str
    github_repo: str
    changelog_type: Optional[str] = None
    changelog_path: Optional[str] = None


# Global rate limiter for GitHub API requests
@sleep_and_retry
@limits(calls=30, period=60)
def github_api_call():
    pass


def rate_limited(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        github_api_call()
        return func(*args, **kwargs)

    return wrapper


@rate_limited
def get_repo(repo):
    return repo


@rate_limited
def check_for_changelog_or_releases(repo):
    changelog_files = [
        "CHANGELOG.md",
        "CHANGELOG.rst",
        "CHANGES.md",
        "CHANGES.rst",
        "HISTORY.md",
        "HISTORY.rst",
        "RELEASES.md",
        "RELEASES.rst",
        "NEWS.md",
        "NEWS.rst",
    ]
    for file in changelog_files:
        try:
            repo.get_contents(file)
            return {"type": "file", "path": file}
        except GithubException:
            continue
    try:
        releases = repo.get_releases()
        if releases.totalCount > 0:
            return {"type": "github_releases", "path": None}
    except GithubException:
        pass

    return None


def search_top_python_repos(limit=1000):
    """unfortunately github search is rate limited to be very slow"""
    g = Github(settings.GITHUB_TOKEN)
    query = "language:python"
    repos = g.search_repositories(
        query=query,
        sort="stars",
        order="desc",
    )

    console.print(
        f"[bold green]Searching for top {limit} Python repositories...[/bold green]"
    )
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
    ) as progress:
        task = progress.add_task("[cyan]Fetching repos...", total=limit)
        top_repos = []
        for repo in repos:
            top_repos.append(repo)
            progress.update(task, advance=1)
            if len(top_repos) >= limit:
                break
            if len(top_repos) % 30 == 0:
                time.sleep(6)

    console.print(f"[bold green]Found {len(top_repos)} repositories.[/bold green]")
    return top_repos


def process_repos(repos, existing_data, file_path):
    console.print("[bold green]Processing repositories...[/bold green]")
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
    ) as progress:
        task = progress.add_task("[cyan]Processing...", total=len(repos))
        for repo in repos:
            try:
                repo = get_repo(repo)  # Apply rate limiting to each repo access
                if repo.full_name in existing_data:
                    package_info = existing_data[repo.full_name]
                    progress.print(
                        f"[yellow]Using existing data for {repo.full_name}[/yellow]"
                    )
                else:
                    changelog_info = check_for_changelog_or_releases(repo)
                    package_info = PackageInfo(
                        name=repo.name,
                        github_repo=repo.full_name,
                        changelog_type=changelog_info["type"]
                        if changelog_info
                        else None,
                        changelog_path=changelog_info["path"]
                        if changelog_info
                        else None,
                    )
                    progress.print(f"[green]Processed {repo.full_name}[/green]")

                # Write the package info to file immediately
                append_to_json_file(file_path, package_info.dict())

            except GithubException as e:
                progress.print(
                    f"[red]Error processing repo {repo.full_name}: {str(e)}[/red]"
                )
            progress.update(task, advance=1)

    console.print(f"[bold green]Processed {len(repos)} repositories.[/bold green]")


def append_to_json_file(file_path: str, data: Dict):
    try:
        with open(file_path, "r+") as file:
            file.seek(0, 2)  # Move to the end of the file
            position = file.tell() - 1
            file.seek(position)
            file.write(
                ",\n" if position > 1 else "\n"
            )  # Add a comma if not the first item
            json.dump(data, file)
            file.write("]")
    except FileNotFoundError:
        with open(file_path, "w") as file:
            json.dump([data], file)


def load_existing_data(file_path):
    try:
        with open(file_path, "r") as f:
            data = json.load(f)
        return {item["github_repo"]: PackageInfo(**item) for item in data}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def main():
    file_path = "package_changelogs.json"
    existing_data = load_existing_data(file_path)
    console.print(
        f"[bold blue]Loaded {len(existing_data)} existing package infos.[/bold blue]"
    )

    if not existing_data:
        with open(file_path, "w") as f:
            json.dump([], f)

    top_repos = search_top_python_repos()
    process_repos(top_repos, existing_data, file_path)

    console.print(f"[bold green]Saved package infos to {file_path}[/bold green]")


if __name__ == "__main__":
    main()
