from enum import Enum

from pydantic import BaseModel


class ChangeLogRetrievalStatus(Enum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    NOT_FOUND = "NOT_FOUND"


class ChangelogRetrievalResult(BaseModel):
    status: ChangeLogRetrievalStatus
    changelog: str = ""
    summary: str = ""
