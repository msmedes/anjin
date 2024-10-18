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
Analyze the following changelog for the Python package '{package}' and provide a concise, actionable summary of changes between the currently used version and the latest version. Focus on:

1. Breaking changes
2. API modifications
3. New features
4. Deprecations
5. Performance improvements
6. Security updates

Ignore minor bug fixes, documentation updates, or internal changes unless they seem particularly impactful.

Format your response as follows:
1. TL;DR (50 words max): Brief overview of changes and their potential impact on the codebase.
2. Detailed summary (bullet points, 200 words max):
   - Breaking changes
   - New features and API modifications
   - Deprecations
   - Performance and security updates
3. Action items (if any): Suggest 1-3 specific steps to adapt the codebase to these changes.

Consider how these changes might affect the given code snippets and the project's dependencies.

Changelog:
{changelog}

Relevant code snippets from the codebase:
{codebase_sample}

Project requirements:
{requirements_content}

Provide your analysis:
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
