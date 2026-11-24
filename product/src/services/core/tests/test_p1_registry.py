"""P1 注册点骨架契约测试。"""

from __future__ import annotations

import pytest

from app.adapters.sources.registry import SourceAdapterRegistry, source_adapter_registry
from app.domain.models import SourcePlatform


def test_register_and_resolve_roundtrip() -> None:
    registry = SourceAdapterRegistry()
    sentinel = object()
    registry.register(SourcePlatform.BILIBILI, sentinel)
    assert registry.resolve(SourcePlatform.BILIBILI) is sentinel
    assert registry.resolve(SourcePlatform.ZHIHU) is None
    assert registry.registered_platforms() == (SourcePlatform.BILIBILI,)


def test_duplicate_registration_is_rejected() -> None:
    registry = SourceAdapterRegistry()
    registry.register(SourcePlatform.ZHIHU, object())
    with pytest.raises(ValueError, match="重复注册"):
        registry.register(SourcePlatform.ZHIHU, object())


def test_global_registry_starts_empty_for_p1() -> None:
    # P1 阶段不接线：全局注册点必须保持为空，link.py 内联路径保持原样。
    assert len(source_adapter_registry) == 0
