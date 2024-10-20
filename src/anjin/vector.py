"""
When this is first run on a codebase, we will chunk the codebase and
store the embeddings in a local instance of chromadb.

On subsequent runs, we will see if we need to reindex the codebase.

To enable this, we will store the hash of the file in the cache directory.
This file will be a json file with the following structure:
[
    <file_path>: {
        "file_hash": "<hash>",
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
import re
from datetime import datetime
from pathlib import Path
from typing import Generator, NamedTuple

import chromadb
from chromadb.config import Settings
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn


class FileToIndex(NamedTuple):
    file_path: str
    file_hash: str
    content: str


class ChromaIndex:
    def __init__(self, codebase_path: str, console: Console):
        self.codebase_path = codebase_path
        self.console = console
        self.index_cache_dir = Path.home() / ".anjin_cache" / "index"
        self.files_to_index = []
        self.files_to_delete = set()
        self.all_file_paths = set()
        self._client = chromadb.PersistentClient(
            settings=Settings(anonymized_telemetry=False)
        )
        self._collection_name = self.codebase_path[1:].replace("/", "-")
        self._collection = self._client.get_or_create_collection(self._collection_name)

        self.index_cache_dir.mkdir(parents=True, exist_ok=True)
        self.index_cache = {}
        if (self.index_cache_dir / "index.json").exists():
            with open(self.index_cache_dir / "index.json", "r") as f:
                self.index_cache = json.load(f)

    def _generate_file_content_hash(self, content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _get_stored_file_hash(self, file_path: str) -> str:
        return self.index_cache.get(file_path, {}).get("file_hash")

    def _hashes_match(self, current_file_hash: str, stored_file_hash: str) -> bool:
        return current_file_hash == stored_file_hash

    def _get_files_to_delete(self):
        self.files_to_delete = self.index_cache.keys() - self.all_file_paths

    def _chunk_file_content(
        self, content: str, max_chunk_size: int = 1000, overlap: int = 100
    ) -> list[str]:
        return self._recursive_chunk_with_overlap(content, max_chunk_size, overlap)

    def _add_files_to_vector_db(self, progress: Progress):
        task = progress.add_task("Indexing codebase", total=len(self.files_to_index))
        for file_to_index in self.files_to_index:
            chunks = self._chunk_file_content(file_to_index.content)
            chunk_ids = [self._generate_file_content_hash(chunk) for chunk in chunks]
            self._collection.add(
                metadatas=[{"file_path": file_to_index.file_path}] * len(chunks),
                documents=chunks,
                ids=chunk_ids,
            )
            progress.update(task, advance=1)

    def _handle_file(self, file_path: str):
        self.all_file_paths.add(file_path)
        with open(file_path, "r") as f:
            current_file_content = f.read()
            current_file_content = re.sub(r"\n", "", current_file_content)
            current_file_hash = self._generate_file_content_hash(current_file_content)
            stored_file_hash = self._get_stored_file_hash(file_path)
            if not stored_file_hash or (
                stored_file_hash and current_file_hash != stored_file_hash
            ):
                self.files_to_index.append(
                    FileToIndex(file_path, current_file_hash, current_file_content)
                )

    def _walk_file_tree(self) -> Generator[str, None, None]:
        for root, _, files in os.walk(self.codebase_path):
            for file in files:
                if not file.endswith(".py"):
                    continue
                file_path = os.path.join(root, file)
                yield file_path

    def _scan_codebase(self):
        for file_path in self._walk_file_tree():
            self._handle_file(file_path)

    def _remove_file_from_index_cache(self, file_path: str):
        del self.index_cache[file_path]

    def _handle_files_to_delete(self):
        self._get_files_to_delete()
        for file_path in self.files_to_delete:
            self._collection.delete(where={"file_path": file_path})
            self._remove_file_from_index_cache(file_path)

    def _update_index_cache(self):
        for file_to_index in self.files_to_index:
            self.index_cache[file_to_index.file_path] = {
                "file_hash": file_to_index.file_hash,
                "indexed_at": datetime.now().isoformat(),
            }

    def _handle_files_to_add(self, progress: Progress):
        self._add_files_to_vector_db(progress)
        self._update_index_cache()

    def _write_index_cache(self):
        with open(self.index_cache_dir / "index.json", "w") as f:
            json.dump(self.index_cache, f)

    def index_codebase(self):
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            console=self.console,
        ) as progress:
            self._scan_codebase()
            self._handle_files_to_add(progress)
            self._handle_files_to_delete()
            self._write_index_cache()

    def _recursive_chunk_with_overlap(
        self, text: str, max_chunk_size: int = 500, overlap: int = 50
    ) -> list[str]:
        if len(text) <= max_chunk_size:
            return [text]

        chunks = []
        start = 0
        while start < len(text):
            end = start + max_chunk_size
            if end > len(text):
                end = len(text)

            chunk = text[start:end]
            chunks.append(chunk)

            start += max_chunk_size - overlap

        return chunks
