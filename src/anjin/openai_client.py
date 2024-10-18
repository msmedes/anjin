from openai import AsyncOpenAI

from anjin.changelog_registry import ChangeLogRetrievalStatus
from anjin.config import settings
from anjin.get_snippets import get_relevant_code_snippets


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
        client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
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
