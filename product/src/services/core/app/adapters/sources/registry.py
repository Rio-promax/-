"""Platform source-adapter registry (P1 skeleton).

单一职责：汇总各平台来源适配器，供 `link.prepare_link_imports` 与
`detect_platform` 在 I1–I4 整合包中切换为"从注册表取适配器"。
本骨架阶段只提供注册与解析数据结构，不接入任何调用方；
平台差异一律留在各适配器文件内，不在此处堆积条件分支。

接入契约（I1 整合包执行，本包不实现）：
- 每个适配器提供 `platform`（`SourcePlatform` 值）与 `can_handle/probe/acquire`
  形态（`app/ports/providers.py::SourceAdapter`）。
- 注册顺序即探测优先级；同名平台重复注册视为编程错误。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

from app.domain.models import SourcePlatform


@dataclass(frozen=True, slots=True)
class RegisteredAdapter:
    """One platform adapter entry. The adapter object shape is defined by I1."""

    platform: SourcePlatform
    adapter: object


class SourceAdapterRegistry:
    """Ordered registry of platform source adapters."""

    def __init__(self) -> None:
        self._entries: dict[SourcePlatform, RegisteredAdapter] = {}

    def register(self, platform: SourcePlatform, adapter: object) -> None:
        if platform in self._entries:
            raise ValueError(f"平台适配器重复注册: {platform.value}")
        self._entries[platform] = RegisteredAdapter(platform=platform, adapter=adapter)

    def resolve(self, platform: SourcePlatform) -> object | None:
        entry = self._entries.get(platform)
        return entry.adapter if entry else None

    def registered_platforms(self) -> tuple[SourcePlatform, ...]:
        return tuple(entry.platform for entry in self._entries.values())

    def __iter__(self) -> Iterator[RegisteredAdapter]:
        return iter(self._entries.values())

    def __len__(self) -> int:
        return len(self._entries)


# 全局注册点。I1–I4 整合包在此登记各平台适配器；在此之前保持为空，
# link.py 的现有内联路径保持原样（P1 不接线，避免无适配器可注册的空窗）。
source_adapter_registry = SourceAdapterRegistry()
