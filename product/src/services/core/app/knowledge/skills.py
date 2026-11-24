"""Discover and load user-selectable summary Skill files."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

SKILL_FILE_SUFFIXES = frozenset({".md", ".markdown", ".txt"})


class SkillFileError(ValueError):
    """Raised when a configured Skill file cannot be safely read."""


@dataclass(frozen=True, slots=True)
class SkillDocument:
    path: str
    name: str
    content: str
    sha256: str

    @property
    def size(self) -> int:
        return len(self.content.encode("utf-8"))

    def metadata(self) -> dict[str, str | int]:
        return {
            "path": self.path,
            "name": self.name,
            "sha256": self.sha256,
            "size": self.size,
        }


def list_skill_documents(root: Path) -> list[SkillDocument]:
    resolved_root = root.expanduser().resolve()
    if not resolved_root.is_dir():
        return []
    documents: list[SkillDocument] = []
    for path in sorted(resolved_root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SKILL_FILE_SUFFIXES:
            continue
        try:
            documents.append(_read_skill_file(resolved_root, path))
        except SkillFileError:
            # A malformed optional Skill should not prevent the rest of the catalog
            # from being displayed; selecting it will return the precise error.
            continue
    return documents


def load_skill_document(root: Path, relative_path: str) -> SkillDocument:
    normalized = relative_path.strip().replace("\\", "/").strip("/")
    if not normalized:
        raise SkillFileError("Skill 文件路径不能为空")
    candidate = (root.expanduser().resolve() / Path(*normalized.split("/"))).resolve()
    resolved_root = root.expanduser().resolve()
    if candidate != resolved_root and resolved_root not in candidate.parents:
        raise SkillFileError("Skill 文件必须位于产品 Skill 存储目录内")
    if candidate.suffix.lower() not in SKILL_FILE_SUFFIXES:
        raise SkillFileError("只支持 Markdown 或纯文本 Skill 文件")
    if not candidate.is_file():
        raise SkillFileError(f"找不到 Skill 文件：{normalized}")
    return _read_skill_file(resolved_root, candidate)


def _read_skill_file(root: Path, path: Path) -> SkillDocument:
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise SkillFileError(f"无法读取 Skill 文件：{path.name}") from error
    if not content.strip():
        raise SkillFileError(f"Skill 文件为空：{path.name}")
    relative_path = path.resolve().relative_to(root).as_posix()
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return SkillDocument(relative_path, path.name, content, digest)
