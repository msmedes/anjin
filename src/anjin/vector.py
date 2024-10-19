"""
When this is first run on a codebase, we will chunk the codebase and
store the embeddings in a local instance of chromadb.

On subsequent runs, we will see if we need to reindex the codebase.

To enable this, we will store the hash of the file in the cache directory.
This file will be a json file with the following structure:
[
    <file_path>: {
        "hash": "<hash>",
        "indexed_at": "<timestamp>"
    }
]
If the hash of the file has changed, we will update the hash and timestamp in the cache.
If the file is no longer in the codebase, we will remove it from the vector db.
If the file has changed, we will remove the existing embeddings
from the vector db and add the new embeddings.
"""

import hashlib
import json
import os
from pathlib import Path
from typing import NamedTuple

import chromadb


class FileToIndex(NamedTuple):
    file_path: str
    hash: str
    content: str


class ChromaIndex:
    def __init__(self, codebase_path: str):
        self.codebase_path = codebase_path
        self.index_cache_dir = Path.home() / ".anjin_cache" / "index"
        self.files_to_index = set()
        self.files_to_delete = set()
        self.all_file_paths = set()
        self._client = chromadb.Client()
        self._collection = self._client.get_or_create_collection(
            self.codebase_path[1:].replace("/", "-")
        )

        self.index_cache_dir.mkdir(parents=True, exist_ok=True)
        self.index_cache = {}
        if (self.index_cache_dir / "index.json").exists():
            with open(self.index_cache_dir / "index.json", "r") as f:
                self.index_cache = json.load(f)

    def _generate_file_content_hash(self, content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _get_stored_file_hash(self, file_path: str) -> str:
        return self.index_cache.get(file_path, {}).get("hash")

    def _hashes_match(self, current_file_hash: str, stored_file_hash: str) -> bool:
        return current_file_hash == stored_file_hash

    def _get_files_to_delete(self):
        for file_path in self.index_cache:
            if file_path not in self.all_file_paths:
                self.files_to_delete.add(file_path)

    def index_codebase(self):
        for root, _, files in os.walk(self.codebase_path):
            for file in files:
                if not file.endswith(".py"):
                    continue
                file_path = os.path.join(root, file)
                self.all_file_paths.add(file_path)
                with open(file_path, "r") as f:
                    current_file_content = f.read()
                    current_file_hash = self._generate_file_content_hash(
                        current_file_content
                    )
                    stored_file_hash = self._get_stored_file_hash(file_path)
                    if not stored_file_hash or (
                        stored_file_hash and current_file_hash != stored_file_hash
                    ):
                        self.files_to_index.add(
                            FileToIndex(
                                file_path, current_file_hash, current_file_content
                            )
                        )

        print(f"number of all file paths: {len(self.all_file_paths)}")
        print(f"number of files to index: {len(self.files_to_index)}")
        print(f"number of files to delete: {len(self.files_to_delete)}")
