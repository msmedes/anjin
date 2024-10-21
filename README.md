# anjin

`anjin` is a tool to help you understand the impact of a new release of a Python package.  It is extremely rough around the edges.  It will not guide you to the coast of feudal Japan in order to establish a trade route to compete with the Portuguese.

To run:
- [install rye](https://rye.astral.sh/guide/installation/)
- `rye sync`
- `rye run anjin -r <requirements file> -c <codebase path>`

Right now accepts absolute paths to the requirements file and codebase.

If you do not want to use the cache, you can run add the `--no-cache` | `-nc` flag.

You will need to set the OPENAI_API_KEY and GITHUB_TOKEN environment variables in a `.env` file

You can mark packages to be ignored by adding `# anjin:ignore` to the dep in the requirements file.

By default, the output will be saved to `dependency_updates.html`. You can set this path with the `-o` flag. I have included an example `dependency_updates.html` in the repo.