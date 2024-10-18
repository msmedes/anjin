import json
from pathlib import Path
from typing import Optional


class ChangelogCache:
    def __init__(self):
        self.cache_dir = Path.home() / ".anjin_cache" / "changelogs"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_cache_file(self, package: str) -> Path:
        return self.cache_dir / f"{package}.json"

    def load(self, package: str) -> dict:
        cache_file = self._get_cache_file(package)
        if cache_file.exists():
            with open(cache_file, "r") as f:
                return json.load(f)
        return {}

    def save(self, package: str, cache: dict):
        cache_file = self._get_cache_file(package)
        with open(cache_file, "w") as f:
            json.dump(cache, f)

    def get(
        self, package: str, current_version: str, latest_version: str
    ) -> Optional[str]:
        cache = self.load(package)
        return cache.get(f"{current_version}_{latest_version}")

    def set(
        self, package: str, current_version: str, latest_version: str, changelog: str
    ):
        cache = self.load(package)
        cache[f"{current_version}_{latest_version}"] = changelog
        self.save(package, cache)

    def contains(self, package: str, current_version: str, latest_version: str) -> bool:
        cache = self.load(package)
        return f"{current_version}_{latest_version}" in cache
