import ast
import asyncio
from pathlib import Path


class PackageUsageVisitor(ast.NodeVisitor):
    def __init__(self, package_name: str):
        self.package_name = package_name
        self.usages: set[tuple[int, str]] = set()

    def visit_Import(self, node):
        for alias in node.names:
            if alias.name == self.package_name:
                self.usages.add((node.lineno, f"Import {self.package_name}"))

    def visit_ImportFrom(self, node):
        if node.module == self.package_name:
            imports = ", ".join(alias.name for alias in node.names)
            self.usages.add((node.lineno, f"From {self.package_name} import {imports}"))

    def visit_Call(self, node):
        if isinstance(node.func, ast.Attribute) and isinstance(
            node.func.value, ast.Name
        ):
            if node.func.value.id == self.package_name:
                self.usages.add(
                    (node.lineno, f"Call {self.package_name}.{node.func.attr}()")
                )
        elif isinstance(node.func, ast.Name) and node.func.id.startswith(
            f"{self.package_name}."
        ):
            self.usages.add((node.lineno, f"Call {node.func.id}()"))


async def get_relevant_code_snippets(
    codebase_path: str, package_name: str, max_snippets: int = 20
) -> list[str]:
    snippets = []
    unique_usages = set()
    codebase_path = Path(codebase_path)

    async def process_file(file_path: Path):
        if file_path.suffix != ".py":
            return

        try:
            content = await asyncio.to_thread(file_path.read_text)
            tree = ast.parse(content)
            visitor = PackageUsageVisitor(package_name)
            visitor.visit(tree)

            if visitor.usages:
                lines = content.splitlines()
                for lineno, usage_desc in visitor.usages:
                    if usage_desc not in unique_usages:
                        unique_usages.add(usage_desc)
                        start = max(0, lineno - 1)
                        end = min(len(lines), lineno + 2)
                        snippet = (
                            f"File: {file_path.relative_to(codebase_path)}\n{usage_desc}\n"
                            + "\n".join(lines[start:end])
                        )
                        snippets.append(snippet)
                        if len(snippets) >= max_snippets:
                            return True  # Signal to stop processing more files
        except Exception as e:
            print(f"Error processing file {file_path}: {e}")

        return False

    async def walk_directory(directory: Path):
        tasks = []
        for item in directory.iterdir():
            if item.is_file():
                tasks.append(process_file(item))
            elif item.is_dir() and not item.name.startswith("."):
                tasks.append(walk_directory(item))

        results = await asyncio.gather(*tasks)
        if any(results):
            return True  # Signal to stop processing more directories
        return False

    await walk_directory(codebase_path)
    return snippets[:max_snippets]
