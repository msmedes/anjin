import asyncio
import os
import re

import httpx
import typer
from packaging import version as pkg_version
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskID, TextColumn
from rich.table import Table
from typing_extensions import Annotated

from anjin.cache import ChangelogCache
from anjin.changelog_registry import (
    ChangelogRetrievalResult,
    ChangeLogRetrievalStatus,
)
from anjin.config import settings
from anjin.generate_html import generate_html_output
from anjin.openai_client import summarize_changes

# monkey patch the changelog registry to use the github token don't @ me
os.environ["CHANGELOGS_GITHUB_API_TOKEN"] = settings.GITHUB_TOKEN
import changelogs  # noqa

app = typer.Typer()
console = Console()


async def parse_requirements(file_path: str) -> tuple[dict, set]:
    dependencies = {}
    ignored_packages = set()
    with open(file_path, "r") as file:
        for line in file:
            line = line.strip()
            if line.startswith("#"):
                continue  # Skip full-line comments

            # Split the line into the requirement and the comment
            requirement, _, comment = line.partition("#")
            requirement = requirement.strip()

            if not requirement:
                continue  # Skip empty lines

            # Check for inline ignore comment
            if "anjin:ignore" in comment.lower():
                package = requirement.split("==")[0].strip()
                ignored_packages.add(package)
            else:
                match = re.match(r"^([^=<>]+)([=<>]+)(.+)$", requirement)
                if match:
                    package, operator, ver = match.groups()
                    package = package.strip()
                    dependencies[package] = ver.strip()

    return dependencies, ignored_packages


async def get_latest_version(package: str) -> str:
    url = f"https://pypi.org/pypi/{package}/json"
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            if response.status_code == 200:
                return response.json()["info"]["version"]
    except Exception as e:
        print(f"Error fetching latest version for {package}: {str(e)}")
    return None


def filter_changelog_by_version(
    changelog: dict, current_version: str, latest_version: str
) -> str:
    filtered_entries = []
    for version, changes in changelog.items():
        if pkg_version.parse(version) > pkg_version.parse(
            current_version
        ) and pkg_version.parse(version) <= pkg_version.parse(latest_version):
            filtered_entries.append(f"## {version}\n{changes}")
    return "\n\n".join(filtered_entries)


async def fetch_changelog(
    package: str, current_version: str, latest_version: str
) -> ChangelogRetrievalResult:
    if settings.USE_CACHE:
        changelog_cache = ChangelogCache()
        if changelog_cache.contains(package, current_version, latest_version):
            print(f"Using cached changelog for {package}")
            cache = changelog_cache.get(package, current_version, latest_version)
            cache_key = f"{package}_{current_version}_{latest_version}"
            return ChangelogRetrievalResult(
                status=ChangeLogRetrievalStatus.SUCCESS, changelog=cache[cache_key]
            )

    try:
        print("Not using cache for changelog for {package}")
        changelog = changelogs.get(package)
        if changelog:
            filtered_changelog = filter_changelog_by_version(
                changelog, current_version, latest_version
            )
            if settings.USE_CACHE:
                changelog_cache.set(
                    package, current_version, latest_version, filtered_changelog
                )
            return ChangelogRetrievalResult(
                status=ChangeLogRetrievalStatus.SUCCESS, changelog=filtered_changelog
            )
        else:
            return ChangelogRetrievalResult(status=ChangeLogRetrievalStatus.NOT_FOUND)
    except Exception as e:
        print(f"Error fetching changelog for {package}: {str(e)}")
        return ChangelogRetrievalResult(status=ChangeLogRetrievalStatus.FAILURE)


async def process_single_dependency(
    package: str,
    current_version: str,
    codebase_path: str,
    requirements_file: str,
    progress: Progress,
    overall_task: TaskID,
    package_task: TaskID,
    ignored_packages: set[str],
):
    if package in ignored_packages:
        progress.update(
            package_task, completed=100, description=f"[yellow]Ignored {package}"
        )
        progress.update(overall_task, advance=1)
        return None

    progress.update(package_task, advance=0, description=f"[cyan]Processing {package}")

    # Get latest version
    latest_version = await get_latest_version(package)
    progress.update(
        package_task, advance=25, description=f"[cyan]Checking version for {package}"
    )
    if not latest_version or pkg_version.parse(latest_version) <= pkg_version.parse(
        current_version
    ):
        progress.update(
            package_task, advance=75, description=f"[yellow]{package} is up to date"
        )
        progress.update(overall_task, advance=1)
        return None

    # Fetch changelog
    progress.update(
        package_task,
        advance=25,
        description=f"[cyan]{'Fetching' if not settings.USE_CACHE else 'Checking'} changelog for {package}",
    )
    changelog_result = await fetch_changelog(package, current_version, latest_version)

    if changelog_result.status == ChangeLogRetrievalStatus.SUCCESS:
        progress.update(
            package_task,
            advance=25,
            description=f"[cyan]Summarizing changes for {package}",
        )
        summary = await summarize_changes(
            changelog_result.changelog, package, codebase_path, requirements_file
        )
        changelog_result.summary = summary

    progress.update(
        package_task, completed=100, description=f"[green]Completed {package}"
    )
    progress.update(overall_task, advance=1)
    return package, current_version, latest_version, changelog_result


@app.command()
def check_updates(
    requirements_file: Annotated[
        str, typer.Option("--requirements", "-r", help="Path to the requirements file")
    ],
    codebase_path: Annotated[
        str, typer.Option("--codebase", "-c", help="Path to the codebase")
    ],
    output_html: Annotated[
        str,
        typer.Option("--output-html", "-o", help="Path to output HTML file"),
    ] = "dependency_updates.html",
    console_output: Annotated[
        bool,
        typer.Option("--console", help="Display output in console instead of HTML"),
    ] = False,
    debug: Annotated[
        bool,
        typer.Option(
            "--debug", "-d", help="Enable debug mode, you do not need to use this"
        ),
    ] = False,
    no_cache: Annotated[
        bool,
        typer.Option("--no-cache", "-nc", help="Bypass the cache and fetch fresh data"),
    ] = False,
):
    async def main():
        settings.DEBUG = debug
        settings.USE_CACHE = not no_cache
        console.print("[bold green]Parsing requirements file...[/bold green]")
        dependencies, ignored_packages = await parse_requirements(requirements_file)
        print(dependencies)

        console.print(f"[bold]Found {len(dependencies)} dependencies to check.[/bold]")
        if ignored_packages:
            console.print(
                f"[bold yellow]Ignoring {len(ignored_packages)} packages.[/bold yellow]"
            )

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            console=console,
            expand=True,
        ) as progress:
            overall_task = progress.add_task(
                "[cyan]Overall progress", total=len(dependencies)
            )
            package_tasks = {
                package: progress.add_task(f"[cyan]{package}", total=100, start=False)
                for package in dependencies.keys()
            }

            tasks = [
                process_single_dependency(
                    package,
                    current_version,
                    codebase_path,
                    requirements_file,
                    progress,
                    overall_task,
                    package_tasks[package],
                    ignored_packages,
                )
                for package, current_version in dependencies.items()
            ]

            results = await asyncio.gather(*tasks)

        updates_found = any(result for result in results if result)

        if console_output:
            if updates_found:
                table = Table(title="Dependency Updates")
                table.add_column("Package", style="cyan")
                table.add_column("Current Version", style="magenta")
                table.add_column("Latest Version", style="green")
                table.add_column("Status", style="yellow")
                table.add_column("Summary", style="blue")

                for result in results:
                    if result:
                        package, current_version, latest_version, changelog_result = (
                            result
                        )
                        table.add_row(
                            package,
                            current_version,
                            latest_version,
                            changelog_result.status.value,
                            changelog_result.summary or "N/A",
                        )

                console.print(table)
            else:
                console.print(
                    "[bold green]All dependencies are up to date![/bold green]"
                )
        else:
            generate_html_output(results, output_html)
            console.print(
                f"[bold green]HTML output saved to: {output_html}[/bold green]"
            )

    asyncio.run(main())


if __name__ == "__main__":
    app()
