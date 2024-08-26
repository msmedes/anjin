# anjin: EXTREMELY WIP

`anjin` is a tool to help you understand the impact of a new release of a Python package.  It is extremely rough around the edges.  It will not guide you to the coast of feudal Japan in order to establish a trade route to compete with the Portuguese.

To run:
- [install rye](https://rye.run/docs/installation)
- `rye sync`
- `rye run anjin -r <requirements file> -c <codebase path>`

Right now accepts absolute paths to the requirements file and codebase.  Also probably will not work at all since I am manually finding changelog files in github repos.

You will need to set the OPENAI_API_KEY and GITHUB_TOKEN environment variables in a `.env` file

### anjin "in action"

https://github.com/user-attachments/assets/f837de32-0a0e-4172-9c6a-d81bad04528d

