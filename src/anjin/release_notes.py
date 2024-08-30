import ast
import asyncio
import json
import os
import re
from pathlib import Path

import httpx
import typer
from openai import AsyncOpenAI
from packaging import version as pkg_version
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskID, TextColumn
from rich.table import Table
from typing_extensions import Annotated

from anjin.changelog_registry import (
    ChangelogRetrievalResult,
    ChangeLogRetrievalStatus,
)
from anjin.config import settings

os.environ["CHANGELOGS_GITHUB_API_TOKEN"] = settings.GITHUB_TOKEN
import changelogs  # noqa

app = typer.Typer()
console = Console()

client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

CACHE_DIR = Path.home() / ".anjin_cache"
CACHE_FILE = CACHE_DIR / "changelog_cache.json"


def load_cache():
    if CACHE_FILE.exists():
        with open(CACHE_FILE, "r") as f:
            return json.load(f)
    return {}


def save_cache(cache):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f)


class PackageUsageVisitor(ast.NodeVisitor):
    def __init__(self, package_name: str):
        self.package_name = package_name
        self.usages: set[tuple[int, str]] = set()

    def visit_Import(self, node):
        for alias in node.names:
            if alias.name == self.package_name:
                self.usages.add((node.lineno, f"Import {self.package_name}"))

    def visit_ImportFrom(self, node):
        if node.module == self.package_name:
            imports = ", ".join(alias.name for alias in node.names)
            self.usages.add((node.lineno, f"From {self.package_name} import {imports}"))

    def visit_Call(self, node):
        if isinstance(node.func, ast.Attribute) and isinstance(
            node.func.value, ast.Name
        ):
            if node.func.value.id == self.package_name:
                self.usages.add(
                    (node.lineno, f"Call {self.package_name}.{node.func.attr}()")
                )
        elif isinstance(node.func, ast.Name) and node.func.id.startswith(
            f"{self.package_name}."
        ):
            self.usages.add((node.lineno, f"Call {node.func.id}()"))


async def get_relevant_code_snippets(
    codebase_path: str, package_name: str, max_snippets: int = 20
) -> list[str]:
    snippets = []
    unique_usages = set()
    codebase_path = Path(codebase_path)

    async def process_file(file_path: Path):
        if file_path.suffix != ".py":
            return

        try:
            content = await asyncio.to_thread(file_path.read_text)
            tree = ast.parse(content)
            visitor = PackageUsageVisitor(package_name)
            visitor.visit(tree)

            if visitor.usages:
                lines = content.splitlines()
                for lineno, usage_desc in visitor.usages:
                    if usage_desc not in unique_usages:
                        unique_usages.add(usage_desc)
                        start = max(0, lineno - 1)
                        end = min(len(lines), lineno + 2)
                        snippet = (
                            f"File: {file_path.relative_to(codebase_path)}\n{usage_desc}\n"
                            + "\n".join(lines[start:end])
                        )
                        snippets.append(snippet)
                        if len(snippets) >= max_snippets:
                            return True  # Signal to stop processing more files
        except Exception as e:
            print(f"Error processing file {file_path}: {e}")

        return False

    async def walk_directory(directory: Path):
        tasks = []
        for item in directory.iterdir():
            if item.is_file():
                tasks.append(process_file(item))
            elif item.is_dir() and not item.name.startswith("."):
                tasks.append(walk_directory(item))

        results = await asyncio.gather(*tasks)
        if any(results):
            return True  # Signal to stop processing more directories
        return False

    await walk_directory(codebase_path)
    return snippets[:max_snippets]


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
    cache = load_cache()
    cache_key = f"{package}_{current_version}_{latest_version}"

    if cache_key in cache:
        return ChangelogRetrievalResult(
            status=ChangeLogRetrievalStatus.SUCCESS, changelog=cache[cache_key]
        )

    try:
        changelog = changelogs.get(package)
        if changelog:
            filtered_changelog = filter_changelog_by_version(
                changelog, current_version, latest_version
            )
            cache[cache_key] = filtered_changelog
            save_cache(cache)
            return ChangelogRetrievalResult(
                status=ChangeLogRetrievalStatus.SUCCESS, changelog=filtered_changelog
            )
        else:
            return ChangelogRetrievalResult(status=ChangeLogRetrievalStatus.NOT_FOUND)
    except Exception as e:
        print(f"Error fetching changelog for {package}: {str(e)}")
        return ChangelogRetrievalResult(status=ChangeLogRetrievalStatus.FAILURE)


async def summarize_changes(
    changelog: str, package: str, codebase_path: str, requirements_file: str
) -> str:
    if changelog in [
        ChangeLogRetrievalStatus.FAILURE,
        ChangeLogRetrievalStatus.NOT_FOUND,
    ]:
        return "Changelog not found"
    snippets = await get_relevant_code_snippets(codebase_path, package)
    codebase_sample = "\n\n".join(snippets)
    with open(requirements_file, "r") as f:
        requirements_content = f.read()

    prompt = f"""
    Analyze the following changelog for the Python package '{package}' and provide a concise summary
    of changes that are likely to be relevant to the given codebase. This changelog only includes
    changes between the currently used version and the latest version. Focus on API changes, new features,
    deprecations, and breaking changes. Ignore minor bug fixes or internal changes unless they seem particularly important.
    No yapping. Do not preface your response with anything like 
    "Here is a summary of the changes" or anything like that. Just give me the summary.
    If there are no relevant changes, just say "No relevant changes".

    Start with a tl;dr summary of the changes and whether they are likely to be relevant to the codebase.

    Changelog:
    {changelog}

    Relevant code snippets from the codebase:
    {codebase_sample}

    Project requirements:
    {requirements_content}

    Provide a concise, brief, bullet-point summary of relevant changes, considering how they might affect the given code snippets:
    """

    if not settings.DEBUG:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful assistant that summarizes changelogs for developers.",
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=1024,
        )
        return response.choices[0].message.content.strip()
    else:
        return "Debug mode"


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
        package_task, advance=25, description=f"[cyan]Fetching changelog for {package}"
    )
    changelog_result = await fetch_changelog(package, current_version, latest_version)

    if changelog_result.status == ChangeLogRetrievalStatus.SUCCESS:
        if changelog_result.changelog.startswith("CACHED:"):
            progress.update(
                package_task,
                advance=25,
                description=f"[cyan]Using cached changelog for {package}",
            )
            changelog_result.changelog = changelog_result.changelog[
                7:
            ]  # Remove "CACHED:" prefix
        else:
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
    debug: Annotated[
        bool,
        typer.Option(
            "--debug", "-d", help="Enable debug mode, you do not need to use this"
        ),
    ] = False,
):
    async def main():
        settings.DEBUG = debug
        console.print("[bold green]Parsing requirements file...[/bold green]")
        dependencies, ignored_packages = await parse_requirements(requirements_file)

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

        table = Table(title="Dependency Updates")
        table.add_column("Package", style="cyan")
        table.add_column("Current Version", style="magenta")
        table.add_column("Latest Version", style="green")
        table.add_column("Status", style="yellow")
        table.add_column("Summary", style="blue")

        updates_found = False
        for result in results:
            if result:
                updates_found = True
                package, current_version, latest_version, changelog_result = result
                table.add_row(
                    package,
                    current_version,
                    latest_version,
                    changelog_result.status.value,
                    changelog_result.summary or "N/A",
                )

        if updates_found:
            console.print(table)
        else:
            console.print("[bold green]All dependencies are up to date![/bold green]")

    asyncio.run(main())


if __name__ == "__main__":
    app()
