import changelogs
import httpx
from packaging import version as pkg_version
from rich.progress import Progress

from anjin.cache import ChangelogCache
from anjin.changelog_registry import ChangelogRetrievalResult, ChangeLogRetrievalStatus
from anjin.config import settings
from anjin.openai_client import summarize_changes


class DependencyRunner:
    def __init__(
        self,
        package: str,
        current_version: str,
        codebase_path: str,
        requirements_file: str,
        progress: Progress,
        overall_task: int,
        ignored: bool,
    ):
        self._package = package
        self._current_version = current_version
        self._codebase_path = codebase_path
        self._requirements_file = requirements_file
        self._progress = progress
        self._overall_task = overall_task
        self._ignored = ignored
        self._latest_version: str | None = None
        self._changelog: str | None = None
        self._changelog_retrieval_status: ChangeLogRetrievalStatus = None
        self._task = self._progress.add_task(
            f"[cyan]{self._package}", total=100, start=True
        )

    async def _get_latest_version(self) -> str:
        url = f"https://pypi.org/pypi/{self._package}/json"
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url)
                if response.status_code == 200:
                    self._latest_version = response.json()["info"]["version"]
        except Exception as e:
            print(f"Error fetching latest version for {self._package}: {str(e)}")
            self._latest_version = None

    def _filter_changelog_by_version(self) -> str:
        filtered_entries = []
        for version, changes in self._changelog.items():
            if pkg_version.parse(version) > pkg_version.parse(
                self._current_version
            ) and pkg_version.parse(version) <= pkg_version.parse(self._latest_version):
                filtered_entries.append(f"## {version}\n{changes}")
        return "\n\n".join(filtered_entries)

    async def _fetch_changelog(self) -> ChangelogRetrievalResult:
        if settings.USE_CACHE:
            changelog_cache = ChangelogCache()
            if changelog_cache.contains(
                self._package, self._current_version, self._latest_version
            ):
                cache = changelog_cache.get(
                    self._package, self._current_version, self._latest_version
                )
                return ChangelogRetrievalResult(
                    status=ChangeLogRetrievalStatus.SUCCESS, changelog=cache
                )

        try:
            changelog = changelogs.get(self._package)
            if changelog:
                filtered_changelog = self._filter_changelog_by_version()
                if settings.USE_CACHE:
                    changelog_cache.set(
                        self._package,
                        self._current_version,
                        self._latest_version,
                        filtered_changelog,
                    )
                self._changelog_retrieval_status = ChangeLogRetrievalStatus.SUCCESS
                self._changelog = filtered_changelog
            else:
                self._changelog_retrieval_status = ChangeLogRetrievalStatus.NOT_FOUND
        except Exception as e:
            print(f"Error fetching changelog for {self._package}: {str(e)}")
            self._changelog_retrieval_status = ChangeLogRetrievalStatus.FAILURE

    def _handle_ignored(self):
        if self._ignored:
            self._progress.update(
                self._task,
                completed=100,
                description=f"[yellow]Ignored {self._package}",
            )
            self._progress.update(self._overall_task, advance=1)
            return True
        return False

    def _handle_up_to_date(self):
        if not self._latest_version or pkg_version.parse(
            self._latest_version
        ) <= pkg_version.parse(self._current_version):
            self._progress.update(
                self._task,
                advance=75,
                description=f"[yellow]{self._package} is up to date",
            )
            self._progress.update(self._overall_task, advance=1)
            self._progress.update(self._task, completed=100)
            return True
        return False

    async def _handle_changelog_result(self):
        if self._changelog_retrieval_status == ChangeLogRetrievalStatus.SUCCESS:
            self._summary = await summarize_changes(
                self._changelog,
                self._package,
                self._codebase_path,
                self._requirements_file,
            )

    async def run(self):
        if self._handle_ignored():
            return

        self._progress.update(
            self._task, advance=0, description=f"[cyan]Processing {self._package}"
        )

        await self._get_latest_version()

        if self._handle_up_to_date():
            return

        self._progress.update(
            self._task,
            advance=25,
            description=f"[cyan]{'Fetching' if not settings.USE_CACHE else 'Checking'} changelog for {self._package}",
        )

        await self._fetch_changelog()
        self._progress.update(
            self._task, advance=50, description="[cyan]Summarizing changelog"
        )

        await self._handle_changelog_result()
        self._progress.update(
            self._task, completed=100, description=f"[green]Completed {self._package}"
        )
        self._progress.update(self._overall_task, advance=1)
