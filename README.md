# anjin

To run:
- [install rye](https://rye.run/docs/installation)
- `rye sync`
- `rye run anjin -r <requirements file> -c <codebase path>`

Right now accepts absolute paths to the requirements file and codebase.  Also probably will not work at all since I am manually finding changelog files in github repos.

You will need to set the OPENAI_API_KEY and GITHUB_TOKEN environment variables in a `.env` file