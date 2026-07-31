"""统一的目标文件访问层：本地目录 / APK(zip) 都用同一套接口读。"""

from __future__ import annotations

import os
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


@dataclass(frozen=True)
class Entry:
    """目标内的一个文件。path 一律用 '/' 分隔的相对路径。"""

    path: str
    size: int

    @property
    def name(self) -> str:
        return self.path.rsplit("/", 1)[-1]

    @property
    def lower(self) -> str:
        return self.path.lower()


class Source:
    kind = "unknown"

    def __init__(self, root: Path) -> None:
        self.root = root

    def entries(self) -> list[Entry]:
        raise NotImplementedError

    def read(self, path: str, limit: int | None = None) -> bytes:
        raise NotImplementedError

    def iter_chunks(self, path: str, chunk: int = 1 << 22) -> Iterator[bytes]:
        raise NotImplementedError

    def local_path(self, path: str) -> Path | None:
        """能落到真实文件系统时返回路径，APK 内部条目返回 None。"""
        return None


class DirSource(Source):
    kind = "dir"

    def entries(self) -> list[Entry]:
        out: list[Entry] = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in {".git", "__pycache__"}]
            for fn in filenames:
                full = Path(dirpath) / fn
                try:
                    size = full.stat().st_size
                except OSError:
                    continue
                out.append(Entry(full.relative_to(self.root).as_posix(), size))
        out.sort(key=lambda e: e.path)
        return out

    def read(self, path: str, limit: int | None = None) -> bytes:
        with open(self.root / path, "rb") as fh:
            return fh.read() if limit is None else fh.read(limit)

    def iter_chunks(self, path: str, chunk: int = 1 << 22) -> Iterator[bytes]:
        with open(self.root / path, "rb") as fh:
            while True:
                buf = fh.read(chunk)
                if not buf:
                    return
                yield buf

    def local_path(self, path: str) -> Path | None:
        return self.root / path


class ApkSource(Source):
    kind = "apk"

    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self._zip = zipfile.ZipFile(root)

    def entries(self) -> list[Entry]:
        return sorted(
            (Entry(i.filename, i.file_size) for i in self._zip.infolist() if not i.is_dir()),
            key=lambda e: e.path,
        )

    def read(self, path: str, limit: int | None = None) -> bytes:
        with self._zip.open(path) as fh:
            return fh.read() if limit is None else fh.read(limit)

    def iter_chunks(self, path: str, chunk: int = 1 << 22) -> Iterator[bytes]:
        with self._zip.open(path) as fh:
            while True:
                buf = fh.read(chunk)
                if not buf:
                    return
                yield buf


def open_source(path: str | Path) -> Source:
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"目标不存在: {p}")
    if p.is_file():
        if p.suffix.lower() in {".apk", ".xapk", ".apks", ".zip", ".ipa"}:
            return ApkSource(p)
        raise ValueError(f"不支持的目标文件类型: {p.suffix}（支持目录或 apk/ipa/zip）")
    return DirSource(p)
