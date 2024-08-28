import json
from enum import Enum
from pydantic import BaseModel, Field, HttpUrl


class ChangelogSource(Enum):
    GITHUB = "github"
    HTTP = "http"


class ChangeLogRetrievalStatus(Enum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    NOT_FOUND = "NOT_FOUND"


class ChangelogInfo(BaseModel):
    source: ChangelogSource
    path: str | HttpUrl
    repo: str | None = None


class ChangelogRetrievalResult(BaseModel):
    status: ChangeLogRetrievalStatus
    changelog: str = ""
    summary: str = ""


def load_changelog_info():
    try:
        with open("package_changelogs.json", "r") as f:
            package_infos = json.load(f)

        changelog_sources = {}
        for info in package_infos:
            if info["changelog_path"]:
                changelog_sources[info["name"]] = ChangelogInfo(
                    source=ChangelogSource.GITHUB,
                    path=info["changelog_path"],
                    repo=info["github_repo"],
                )
        return changelog_sources
    except FileNotFoundError:
        print("package_changelogs.json not found. Run the script to generate it first.")
        return {}


changelog_registry = load_changelog_info()


def get_changelog_info(package_name: str) -> ChangelogInfo | None:
    return changelog_registry.get(package_name)


# The rest of your existing code (ChangeLogRetrievalStatus, ChangelogRetrievalResult) remains unchanged
