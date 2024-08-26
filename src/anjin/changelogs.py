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


class ChangelogRetrievalResult(BaseModel):
    status: ChangeLogRetrievalStatus
    changelog: str = ""
    summary: str = ""


class ChangelogSources(BaseModel):
    cachetools: ChangelogInfo = Field(
        default_factory=lambda: ChangelogInfo(
            source=ChangelogSource.GITHUB, path="CHANGELOG.rst"
        )
    )
    aiomysql: ChangelogInfo = Field(
        default_factory=lambda: ChangelogInfo(
            source=ChangelogSource.GITHUB, path="CHANGES.txt"
        )
    )
    asyncache: ChangelogInfo = Field(
        default_factory=lambda: ChangelogInfo(
            source=ChangelogSource.GITHUB, path="CHANGELOG.rst"
        )
    )
    python_email_validator: ChangelogInfo = Field(
        default_factory=lambda: ChangelogInfo(
            source=ChangelogSource.GITHUB, path="CHANGELOG.md", alias="email-validator"
        )
    )
    cryptography: ChangelogInfo = Field(
        default_factory=lambda: ChangelogInfo(
            source=ChangelogSource.GITHUB, path="CHANGELOG.rst"
        )
    )
    requests: ChangelogInfo = Field(
        default_factory=lambda: ChangelogInfo(
            source=ChangelogSource.HTTP,
            path="https://raw.githubusercontent.com/psf/requests/main/HISTORY.md",
        )
    )
    SQLAlchemy: ChangelogInfo = Field(
        default_factory=lambda: ChangelogInfo(
            source=ChangelogSource.HTTP,
            path="https://docs.sqlalchemy.org/en/20/changelog/changelog_20.html#change-2.0.31",
        )
    )
    alembic: ChangelogInfo = Field(
        default_factory=lambda: ChangelogInfo(
            source=ChangelogSource.HTTP,
            path="https://alembic.sqlalchemy.org/en/latest/changelog.html",
        )
    )
    fastapi: ChangelogInfo = Field(
        default_factory=lambda: ChangelogInfo(
            source=ChangelogSource.HTTP,
            path="https://fastapi.tiangolo.com/release-notes/",
        )
    )
    faker: ChangelogInfo = Field(
        default_factory=lambda: ChangelogInfo(
            source=ChangelogSource.GITHUB,
            path="CHANGELOG.md",
        )
    )
    ruff: ChangelogInfo = Field(
        default_factory=lambda: ChangelogInfo(
            source=ChangelogSource.GITHUB,
            path="CHANGELOG.md",
        )
    )
    google_auth: ChangelogInfo = Field(
        default_factory=lambda: ChangelogInfo(
            source=ChangelogSource.GITHUB,
            path="CHANGELOG.md",
            alias="google-auth",
        )
    )


changelog_sources = ChangelogSources()
