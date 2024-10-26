import asyncio
import os
import re

import typer
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
from rich.table import Table
from typing_extensions import Annotated

from anjin.config import settings
from anjin.dependency import DependencyRunner
from anjin.generate_html import generate_html_output
from anjin.vector import ChromaIndex

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


async def do_stuff(
    requirements_file: str,
    output_html: str,
    console_output: bool,
    codebase_path: str,
):
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

        tasks = [
            DependencyRunner(
                package,
                current_version,
                codebase_path,
                requirements_file,
                progress,
                overall_task,
                package in ignored_packages,
            ).run()
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
                    package, current_version, latest_version, changelog_result = result
                    table.add_row(
                        package,
                        current_version,
                        latest_version,
                        changelog_result.status.value,
                        changelog_result.summary or "N/A",
                    )

            console.print(table)
        else:
            console.print("[bold green]All dependencies are up to date![/bold green]")
    else:
        generate_html_output(results, output_html)
        console.print(f"[bold green]HTML output saved to: {output_html}[/bold green]")


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

        chroma = ChromaIndex(codebase_path, console)
        chroma.index_codebase()
        await do_stuff(requirements_file, output_html, console_output, codebase_path)

    asyncio.run(main())


if __name__ == "__main__":
    app()
