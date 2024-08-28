import json
import time

from github import Github, GithubException
from pydantic import BaseModel
from ratelimit import limits, sleep_and_retry
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn

console = Console()


class PackageInfo(BaseModel):
    name: str
    github_repo: str
    changelog_path: str | None = None


@sleep_and_retry
@limits(calls=30, period=60)
def get_repo(repo):
    return repo


@sleep_and_retry
@limits(calls=30, period=60)
def check_for_changelog(repo):
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
            return file
        except GithubException:
            time.sleep(1)
            continue
    return None


def search_top_python_repos(limit=100):
    g = Github()
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
            if len(top_repos) >= limit:
                break
            top_repos.append(repo)
            progress.update(task, advance=1)
            if len(top_repos) % 30 == 0:
                time.sleep(5)

    console.print(f"[bold green]Found {len(top_repos)} repositories.[/bold green]")
    return top_repos


def process_repos(repos, existing_data):
    package_infos = {}
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
                    changelog_path = check_for_changelog(repo)
                    package_info = PackageInfo(
                        name=repo.name,
                        github_repo=repo.full_name,
                        changelog_path=changelog_path,
                    )
                    progress.print(f"[green]Processed {repo.full_name}[/green]")
                package_infos[repo.full_name] = package_info
            except GithubException as e:
                progress.print(
                    f"[red]Error processing repo {repo.full_name}: {str(e)}[/red]"
                )
            progress.update(task, advance=1)

    console.print(
        f"[bold green]Processed {len(package_infos)} repositories.[/bold green]"
    )
    return package_infos


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

    top_repos = search_top_python_repos()
    package_infos = process_repos(top_repos, existing_data)

    console.print("[bold green]Saving package infos to file...[/bold green]")
    with open(file_path, "w") as f:
        json.dump([info.dict() for info in package_infos.values()], f, indent=2)
    console.print(
        f"[bold green]Saved {len(package_infos)} package infos to {file_path}[/bold green]"
    )


if __name__ == "__main__":
    main()
