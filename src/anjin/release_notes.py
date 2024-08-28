import ast
import asyncio
import os
import re

import httpx
import tiktoken
import typer
from bs4 import BeautifulSoup
from github import Github, Repository
from openai import AsyncOpenAI
from packaging import version as pkg_version
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from typing_extensions import Annotated

from anjin.changelog_registry import (
    ChangelogRetrievalResult,
    ChangeLogRetrievalStatus,
    ChangelogSource,
    changelog_sources,
    changelog_registry,
)
from anjin.config import settings

app = typer.Typer()
console = Console()

client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
tiktoken_encoding = tiktoken.encoding_for_model("gpt-4o-mini")

g = Github(settings.GITHUB_TOKEN)


async def parse_requirements(file_path: str) -> dict:
    dependencies = {}
    with open(file_path, "r") as file:
        content = file.read()
    for line in content.splitlines():
        match = re.match(r"^([^=<>]+)([=<>]+)(.+)$", line.strip())
        if match:
            package, operator, ver = match.groups()
            dependencies[package.strip()] = ver.strip()
    return dependencies


async def get_latest_version(package: str) -> str:
    url = f"https://pypi.org/pypi/{package}/json"
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        if response.status_code == 200:
            return response.json()["info"]["version"]
    return None


async def fetch_github_changelog(repo, changelog_info, current_version, latest_version):
    contents = await asyncio.to_thread(repo.get_contents, changelog_info.path)
    full_changelog = contents.decoded_content.decode()

    # Filter changelog to only include relevant versions
    filtered_changelog = filter_changelog_by_version(
        full_changelog, current_version, latest_version
    )

    return ChangelogRetrievalResult(
        status=ChangeLogRetrievalStatus.SUCCESS, changelog=filtered_changelog
    )


async def fetch_http_changelog(changelog_info, current_version, latest_version):
    async with httpx.AsyncClient() as client:
        response = await client.get(changelog_info.path)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, "html.parser")
            full_changelog = soup.get_text(separator="\n", strip=True)

            # Filter changelog to only include relevant versions
            filtered_changelog = filter_changelog_by_version(
                full_changelog, current_version, latest_version
            )

            return ChangelogRetrievalResult(
                status=ChangeLogRetrievalStatus.SUCCESS, changelog=filtered_changelog
            )
        else:
            return ChangelogRetrievalResult(status=ChangeLogRetrievalStatus.FAILURE)


def filter_changelog_by_version(changelog, current_version, latest_version):
    # This is a simplified version. You may need to adjust it based on the actual changelog format
    lines = changelog.split("\n")
    filtered_lines = []
    include = False
    for line in lines:
        if line.strip().startswith(latest_version):
            include = True
        if line.strip().startswith(current_version):
            break
        if include:
            filtered_lines.append(line)
    return "\n".join(filtered_lines)


async def fetch_changelog(
    package: str, current_version: str, latest_version: str
) -> ChangelogRetrievalResult:
    try:
        changelog_info = getattr(changelog_sources, package, None)
        if not changelog_info:
            return ChangelogRetrievalResult(status=ChangeLogRetrievalStatus.NOT_FOUND)

        if changelog_info.source == ChangelogSource.GITHUB:
            repo = await find_github_repo(package)
            if repo:
                return await fetch_github_changelog(
                    repo, changelog_info, current_version, latest_version
                )
            else:
                return ChangelogRetrievalResult(
                    status=ChangeLogRetrievalStatus.NOT_FOUND
                )
        elif changelog_info.source == ChangelogSource.HTTP:
            return await fetch_http_changelog(
                changelog_info, current_version, latest_version
            )
        else:
            return ChangelogRetrievalResult(status=ChangeLogRetrievalStatus.NOT_FOUND)

    except Exception as e:
        print(f"Error fetching changelog for {package}: {str(e)}")
        return ChangelogRetrievalResult(status=ChangeLogRetrievalStatus.FAILURE)


async def find_github_repo(package: str) -> Repository.Repository | None:
    changelog_info = changelog_registry.get(package)
    if (
        changelog_info
        and changelog_info.source == ChangelogSource.GITHUB
        and changelog_info.repo
    ):
        try:
            return await asyncio.to_thread(g.get_repo, changelog_info.repo)
        except Exception as e:
            print(f"Error fetching repo for {package}: {str(e)}")
    return None


def find_package_usage(file_path: str, package_name: str) -> list:
    with open(file_path, "r") as file:
        content = file.read()

    tree = ast.parse(content)
    usages = []

    class PackageUsageVisitor(ast.NodeVisitor):
        def visit_Import(self, node):
            for alias in node.names:
                if alias.name == package_name:
                    usages.append((node.lineno, ast.get_source_segment(content, node)))

        def visit_ImportFrom(self, node):
            if node.module == package_name:
                usages.append((node.lineno, ast.get_source_segment(content, node)))

        def visit_Name(self, node):
            if node.id == package_name:
                usages.append((node.lineno, ast.get_source_segment(content, node)))

    PackageUsageVisitor().visit(tree)
    return usages


async def get_relevant_code_snippets(
    codebase_path: str, package_name: str, max_snippets: int = 5
) -> list:
    snippets = []
    for root, _, files in os.walk(codebase_path):
        for file in files:
            if file.endswith(".py"):
                file_path = os.path.join(root, file)
                usages = await asyncio.to_thread(
                    find_package_usage, file_path, package_name
                )
                for lineno, usage in usages:
                    with open(file_path, "r") as f:
                        lines = f.readlines()
                        start = max(0, lineno - 3)
                        end = min(len(lines), lineno + 2)
                        snippet = "".join(lines[start:end])
                        snippets.append(f"File: {file_path}\n{snippet}")
                    if len(snippets) >= max_snippets:
                        return snippets
    return snippets


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


async def process_dependency(
    package: str,
    current_version: str,
    codebase_path: str,
    requirements_file: str,
    progress: Progress,
    task_id: int,
):
    progress.update(task_id, advance=0, description=f"[cyan]Checking {package}...")
    latest_version = await get_latest_version(package)

    if latest_version and pkg_version.parse(latest_version) > pkg_version.parse(
        current_version
    ):
        progress.update(
            task_id, advance=0, description=f"[cyan]Fetching changelog for {package}..."
        )
        changelog_result = await fetch_changelog(
            package, current_version, latest_version
        )

        if changelog_result.status == ChangeLogRetrievalStatus.SUCCESS:
            progress.update(
                task_id,
                advance=0,
                description=f"[cyan]Summarizing changes for {package}...",
            )
            summary = await summarize_changes(
                changelog_result.changelog, package, codebase_path, requirements_file
            )
            changelog_result.summary = summary

        progress.update(task_id, advance=1, description=f"[green]Completed {package}")
        return package, current_version, latest_version, changelog_result
    else:
        progress.update(
            task_id, advance=1, description=f"[yellow]{package} is up to date"
        )
        return None


@app.command()
def check_updates(
    requirements_file: Annotated[
        str, typer.Option("--requirements", "-r", help="Path to the requirements file")
    ],
    codebase_path: Annotated[
        str, typer.Option("--codebase", "-c", help="Path to the codebase")
    ],
    debug: Annotated[
        bool, typer.Option("--debug", "-d", help="Enable debug mode")
    ] = False,
):
    async def main():
        if debug:
            settings.DEBUG = True
        console.print("[bold green]Parsing requirements file...[/bold green]")
        dependencies = await parse_requirements(requirements_file)
        console.print(f"[bold]Found {len(dependencies)} dependencies.[/bold]")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            overall_task = progress.add_task(
                "[cyan]Processing dependencies...", total=len(dependencies)
            )
            tasks = [
                process_dependency(
                    package,
                    current_version,
                    codebase_path,
                    requirements_file,
                    progress,
                    overall_task,
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
