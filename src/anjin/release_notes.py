import ast
import asyncio
import os
import re
from enum import Enum

import httpx
import typer
from github import Github
from openai import AsyncOpenAI
from packaging import version
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from dotenv import load_dotenv

load_dotenv()

app = typer.Typer()
console = Console()

# Initialize OpenAI client
client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Initialize GitHub client
g = Github(os.getenv("GITHUB_TOKEN"))

change_dict = {
    "cachetools": "CHANGELOG.rst",
    "aiomysql": "CHANGES.txt",
    "asyncache": "CHANGELOG.rst",
    "email-validator": "CHANGELOG.md",
    "cryptography": "CHANGELOG.rst",
}


class ChangeLogRetrievalStatus(Enum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    NOT_FOUND = "NOT_FOUND"


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


async def fetch_changelog(package: str, version: str) -> str:
    try:
        # Search for the package on GitHub
        repo = await asyncio.to_thread(
            g.search_repositories, f"{package} language:python"
        )
        repo = repo[0]
        repo.get_contents(change_dict.get(package, "CHANGELOG.rst"))

        # Try to fetch the changelog file
        contents = await asyncio.to_thread(
            repo.get_contents, change_dict.get(package, "CHANGELOG.rst")
        )
        changelog = contents.decoded_content.decode()
        changelog = contents.decoded_content.decode()

        return changelog
    except Exception as e:
        print(f"Error fetching changelog for {package}: {str(e)}")
        return ChangeLogRetrievalStatus.FAILURE


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
    print(snippets)
    return snippets


async def summarize_changes(changelog: str, package: str, codebase_path: str) -> str:
    if changelog in [
        ChangeLogRetrievalStatus.FAILURE,
        ChangeLogRetrievalStatus.NOT_FOUND,
    ]:
        return "Changelog not found"
    snippets = await get_relevant_code_snippets(codebase_path, package)
    codebase_sample = "\n\n".join(snippets)

    prompt = f"""
    Analyze the following changelog for the Python package '{package}' and provide a concise summary of changes that are likely to be relevant to the given codebase. Focus on API changes, new features, deprecations, and breaking changes. Ignore minor bug fixes or internal changes unless they seem particularly important.
    No blabbing.  Do not preface your response with anything like "Here is a summary of the changes" or anything like that.  Just give me the summary.
    If there are no relevant changes, just say "No relevant changes".

    Start with a tl;dr summary of the changes and whether they are likely to be relevant to the codebase.

    Changelog:
    {changelog}

    Relevant code snippets from the codebase:
    {codebase_sample}

    Provide a concise, brief, bullet-point summary of relevant changes, considering how they might affect the given code snippets:
    """

    # print(prompt)

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


async def process_dependency(
    package: str,
    current_version: str,
    codebase_path: str,
    progress: Progress,
    task_id: int,
):
    progress.update(task_id, advance=0, description=f"[cyan]Checking {package}...")
    latest_version = await get_latest_version(package)

    if latest_version and version.parse(latest_version) > version.parse(
        current_version
    ):
        progress.update(
            task_id, advance=0, description=f"[cyan]Fetching changelog for {package}..."
        )
        changelog = await fetch_changelog(package, latest_version)

        progress.update(
            task_id,
            advance=0,
            description=f"[cyan]Summarizing changes for {package}...",
        )
        summary = await summarize_changes(changelog, package, codebase_path)

        progress.update(task_id, advance=1, description=f"[green]Completed {package}")
        return package, current_version, latest_version, summary
    else:
        progress.update(
            task_id, advance=1, description=f"[yellow]{package} is up to date"
        )
        return None


@app.command()
def check_updates(
    requirements_file: str = typer.Option("--requirements", "-r", help="Path to the requirements file"),
    codebase_path: str = typer.Option("--codebase", "-c", help="Path to the codebase"),
):
    async def main():
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
            items = [
                item
                for item in dependencies.items()
                if item[0] in ["asyncache", "cachetools", "cryptography"]
            ]
            tasks = [
                process_dependency(
                    package, current_version, codebase_path, progress, overall_task
                )
                for package, current_version in items
            ]

            results = await asyncio.gather(*tasks)

        table = Table(title="Dependency Updates")
        table.add_column("Package", style="cyan")
        table.add_column("Current Version", style="magenta")
        table.add_column("Latest Version", style="green")
        table.add_column("Summary", style="yellow")

        updates_found = False
        summary_styles = ["yellow", "blue", "pink3"]
        for index, result in enumerate(results):
            if result:
                updates_found = True
                summary_style = summary_styles[index % len(summary_styles)]
                table.add_row(*result, style=summary_style)

        if updates_found:
            console.print(table)
        else:
            console.print("[bold green]All dependencies are up to date![/bold green]")

    asyncio.run(main())


if __name__ == "__main__":
    app()
