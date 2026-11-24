"""Persistence for rebuildable RAG taxonomy and durable ask sessions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select, union

from app.db.models import (
    ContentRagDetailTagRow,
    ContentTopicRow,
    ContentFavoriteFolderRow,
    ContentRow,
    ContentTagRow,
    FavoriteFolderRow,
    RagCoverageRow,
    RagAnswerFeedbackRow,
    RagDetailTagRow,
    RagDeveloperTagReviewRow,
    RagFeedbackEventRow,
    RagTopicRow,
    RagQueryRow,
    RagScanItemRow,
    RagSessionRow,
    TagRow,
    RagTopicRow,
)
from app.domain.models import new_id
from app.knowledge.rag_catalog import (
    CATALOG_VERSION,
    TOPICS,
    validate_detail_tag,
    validate_topic_ids,
)


class RagStore:
    def __init__(self, store) -> None:
        self.store = store
        self.initialize_catalog()

    def initialize_catalog(self) -> None:
        now = datetime.now(UTC)
        with self.store.session_factory.begin() as session:
            for topic in TOPICS:
                row = session.get(RagTopicRow, topic.id)
                if row is None:
                    session.add(RagTopicRow(
                        id=topic.id,
                        name=topic.name,
                        description=topic.description,
                        catalog_version=CATALOG_VERSION,
                        updated_at=now,
                    ))
                else:
                    row.name = topic.name
                    row.description = topic.description
                    row.catalog_version = CATALOG_VERSION
                    row.updated_at = now

    def list_topics(self) -> list[dict]:
        with self.store.session_factory() as session:
            rows = session.execute(select(RagTopicRow).order_by(RagTopicRow.id)).scalars().all()
        return [{"id": row.id, "name": row.name, "description": row.description,
                 "catalog_version": row.catalog_version} for row in rows]

    def graph_view(
        self, *, query: str = "", content_id: str | None = None,
        facet_id: str | None = None, limit: int = 20, offset: int = 0,
    ) -> dict:
        """Project bounded content-to-attribute relations from the current SQLite rows."""

        from app.knowledge.rag_catalog import CATALOG_VERSION

        query = query.strip()[:100]
        limit = min(50, max(1, int(limit)))
        offset = max(0, int(offset))
        has_more = False
        total_count = 0
        with self.store.session_factory() as session:
            if content_id:
                seed = session.get(ContentRow, content_id)
                if seed is None or seed.deleted_at is not None:
                    return {"selected_content_id": content_id, "nodes": [], "edges": [],
                            "related_content_ids": [], "page": {"offset": offset, "limit": limit,
                            "count": 0, "total_count": 0, "has_more": False, "truncated": False},
                            "relation_coverage": {}}
                folder_ids = session.execute(select(ContentFavoriteFolderRow.folder_id).where(
                    ContentFavoriteFolderRow.content_id == seed.id,
                )).scalars().all()
                user_tag_ids = session.execute(select(ContentTagRow.tag_id).where(
                    ContentTagRow.content_id == seed.id,
                )).scalars().all()
                topic_ids = session.execute(select(ContentTopicRow.topic_id).join(
                    RagTopicRow, RagTopicRow.id == ContentTopicRow.topic_id,
                ).where(
                    ContentTopicRow.content_id == seed.id,
                    ContentTopicRow.status == "confirmed",
                    RagTopicRow.catalog_version == CATALOG_VERSION,
                )).scalars().all()
                detail_tag_ids = session.execute(select(ContentRagDetailTagRow.tag_id).join(
                    RagDetailTagRow, RagDetailTagRow.id == ContentRagDetailTagRow.tag_id,
                ).where(
                    ContentRagDetailTagRow.content_id == seed.id,
                    ContentRagDetailTagRow.status == "active",
                    RagDetailTagRow.status == "active",
                )).scalars().all()
                related_queries = []
                if folder_ids:
                    related_queries.append(select(ContentFavoriteFolderRow.content_id.label("content_id")).join(
                        ContentRow, ContentRow.id == ContentFavoriteFolderRow.content_id,
                    ).where(ContentFavoriteFolderRow.folder_id.in_(folder_ids),
                            ContentRow.deleted_at.is_(None)))
                if user_tag_ids:
                    related_queries.append(select(ContentTagRow.content_id.label("content_id")).join(
                        ContentRow, ContentRow.id == ContentTagRow.content_id,
                    ).where(ContentTagRow.tag_id.in_(user_tag_ids),
                            ContentRow.deleted_at.is_(None)))
                if topic_ids:
                    related_queries.append(select(ContentTopicRow.content_id.label("content_id")).join(
                        ContentRow, ContentRow.id == ContentTopicRow.content_id,
                    ).join(RagTopicRow, RagTopicRow.id == ContentTopicRow.topic_id).where(
                        ContentTopicRow.topic_id.in_(topic_ids), ContentTopicRow.status == "confirmed",
                        RagTopicRow.catalog_version == CATALOG_VERSION,
                        ContentRow.deleted_at.is_(None),
                    ))
                if detail_tag_ids:
                    related_queries.append(select(ContentRagDetailTagRow.content_id.label("content_id")).join(
                        ContentRow, ContentRow.id == ContentRagDetailTagRow.content_id,
                    ).join(RagDetailTagRow, RagDetailTagRow.id == ContentRagDetailTagRow.tag_id).where(
                            ContentRagDetailTagRow.tag_id.in_(detail_tag_ids),
                            ContentRagDetailTagRow.status == "active",
                            RagDetailTagRow.status == "active", ContentRow.deleted_at.is_(None)))
                related_queries.append(select(ContentRow.id.label("content_id")).where(
                    ContentRow.platform == seed.platform, ContentRow.deleted_at.is_(None),
                ))
                related_queries.append(select(ContentRow.id.label("content_id")).where(
                    ContentRow.kind == seed.kind, ContentRow.deleted_at.is_(None),
                ))
                if seed.author:
                    related_queries.append(select(ContentRow.id.label("content_id")).where(
                        ContentRow.author == seed.author, ContentRow.deleted_at.is_(None),
                    ))
                if seed.favorite:
                    related_queries.append(select(ContentRow.id.label("content_id")).where(
                        ContentRow.favorite.is_(True), ContentRow.deleted_at.is_(None),
                    ))
                related_content = union(*related_queries).subquery()
                total_count = session.scalar(select(func.count()).select_from(related_content).where(
                    related_content.c.content_id != seed.id,
                )) + 1
                neighbor_rows = session.execute(select(ContentRow.id).join(
                    related_content, related_content.c.content_id == ContentRow.id,
                ).where(
                    ContentRow.id != seed.id, ContentRow.deleted_at.is_(None),
                ).order_by(ContentRow.title, ContentRow.id).offset(offset).limit(limit + 1)).scalars().all()
                has_more = len(neighbor_rows) > limit
                neighbor_rows = neighbor_rows[:limit]
                selected_ids = [seed.id, *neighbor_rows]
            elif facet_id:
                kind, _, key = facet_id.partition(":")
                if kind == "platform":
                    matched = select(ContentRow.id).where(ContentRow.platform == key)
                elif kind == "media_type":
                    matched = select(ContentRow.id).where(ContentRow.kind == key)
                elif kind == "author":
                    matched = select(ContentRow.id).where(ContentRow.author == key)
                elif kind == "favorite":
                    matched = select(ContentRow.id).where(ContentRow.favorite.is_(True))
                elif kind == "favorite_folder":
                    matched = select(ContentFavoriteFolderRow.content_id).where(
                        ContentFavoriteFolderRow.folder_id == key,
                    )
                elif kind == "user_tag":
                    matched = select(ContentTagRow.content_id).join(
                        TagRow, TagRow.id == ContentTagRow.tag_id,
                    ).where(ContentTagRow.tag_id == key, TagRow.user_id == "local")
                elif kind == "topic":
                    matched = select(ContentTopicRow.content_id).join(
                        RagTopicRow, RagTopicRow.id == ContentTopicRow.topic_id,
                    ).where(ContentTopicRow.topic_id == key, ContentTopicRow.status == "confirmed",
                            RagTopicRow.catalog_version == CATALOG_VERSION)
                elif kind == "detail_tag":
                    matched = select(ContentRagDetailTagRow.content_id).join(
                        RagDetailTagRow, RagDetailTagRow.id == ContentRagDetailTagRow.tag_id,
                    ).where(ContentRagDetailTagRow.tag_id == key,
                            ContentRagDetailTagRow.status == "active", RagDetailTagRow.status == "active")
                else:
                    matched = None
                total_count = session.scalar(select(func.count(func.distinct(ContentRow.id))).where(
                    ContentRow.id.in_(matched) if matched is not None else False,
                    ContentRow.deleted_at.is_(None),
                )) or 0
                selected_ids = session.execute(select(ContentRow.id).where(
                    ContentRow.id.in_(matched) if matched is not None else False,
                    ContentRow.deleted_at.is_(None),
                ).order_by(ContentRow.title, ContentRow.id).offset(offset).limit(limit + 1)).scalars().all()
                has_more = len(selected_ids) > limit
                selected_ids = selected_ids[:limit]
            else:
                selected_ids: list[str]
                if query:
                    pattern = f"%{query}%"
                    query_sets = [select(ContentRow.id.label("content_id")).where(
                        ContentRow.deleted_at.is_(None),
                        or_(ContentRow.title.ilike(pattern), ContentRow.platform.ilike(pattern),
                            ContentRow.author.ilike(pattern), ContentRow.kind.ilike(pattern)),
                    )]
                    query_sets.append(select(ContentFavoriteFolderRow.content_id.label("content_id")).join(
                        FavoriteFolderRow, FavoriteFolderRow.id == ContentFavoriteFolderRow.folder_id,
                    ).join(ContentRow, ContentRow.id == ContentFavoriteFolderRow.content_id).where(
                        ContentRow.deleted_at.is_(None), FavoriteFolderRow.name.ilike(pattern),
                    ))
                    query_sets.append(select(ContentTagRow.content_id.label("content_id")).join(
                        TagRow, TagRow.id == ContentTagRow.tag_id,
                    ).join(ContentRow, ContentRow.id == ContentTagRow.content_id).where(
                        ContentRow.deleted_at.is_(None), TagRow.user_id == "local", TagRow.name.ilike(pattern),
                    ))
                    query_sets.append(select(ContentTopicRow.content_id.label("content_id")).join(
                        RagTopicRow, RagTopicRow.id == ContentTopicRow.topic_id,
                    ).join(ContentRow, ContentRow.id == ContentTopicRow.content_id).where(
                        ContentRow.deleted_at.is_(None), ContentTopicRow.status == "confirmed",
                        RagTopicRow.catalog_version == CATALOG_VERSION, RagTopicRow.name.ilike(pattern),
                    ))
                    query_sets.append(select(ContentRagDetailTagRow.content_id.label("content_id")).join(
                        RagDetailTagRow, RagDetailTagRow.id == ContentRagDetailTagRow.tag_id,
                    ).join(ContentRow, ContentRow.id == ContentRagDetailTagRow.content_id).where(
                        ContentRow.deleted_at.is_(None), ContentRagDetailTagRow.status == "active",
                        RagDetailTagRow.status == "active", RagDetailTagRow.display_name.ilike(pattern),
                    ))
                    query_matches = union(*query_sets).subquery()
                    total_count = session.scalar(select(func.count()).select_from(query_matches)) or 0
                    selected_ids = session.execute(select(ContentRow.id).join(
                        query_matches, query_matches.c.content_id == ContentRow.id,
                    ).where(ContentRow.deleted_at.is_(None)).order_by(
                        ContentRow.title, ContentRow.id,
                    ).offset(offset).limit(limit + 1)).scalars().all()
                    has_more = len(selected_ids) > limit
                    selected_ids = selected_ids[:limit]
                else:
                    total_count = session.scalar(select(func.count()).select_from(ContentRow).where(
                        ContentRow.deleted_at.is_(None),
                    )) or 0
                    selected_ids = session.execute(select(ContentRow.id).where(
                        ContentRow.deleted_at.is_(None),
                    ).order_by(ContentRow.title, ContentRow.id).offset(offset).limit(limit + 1)).scalars().all()
                    has_more = len(selected_ids) > limit
                    selected_ids = selected_ids[:limit]

            rows = session.execute(select(ContentRow).where(
                ContentRow.id.in_(selected_ids) if selected_ids else False,
                ContentRow.deleted_at.is_(None),
            )).scalars().all()
            rows_by_id = {row.id: row for row in rows}
            nodes: dict[str, dict] = {}
            edges: list[dict] = []

            def add_facet(content: ContentRow, kind: str, key: str, label: str) -> None:
                node_id = f"{kind}:{key}"
                nodes.setdefault(node_id, {"id": node_id, "kind": kind, "label": label})
                edges.append({"source": f"content:{content.id}", "target": node_id, "relation": kind})

            for content in rows:
                nodes[f"content:{content.id}"] = {
                    "id": f"content:{content.id}", "kind": "content", "content_id": content.id,
                    "label": content.title, "platform": content.platform, "author": content.author,
                    "media_type": content.kind, "favorite": bool(content.favorite),
                }
                add_facet(content, "platform", content.platform, content.platform)
                add_facet(content, "media_type", content.kind, content.kind)
                if content.author:
                    add_facet(content, "author", content.author, content.author)
                if content.favorite:
                    add_facet(content, "favorite", "yes", "已收藏")

            if selected_ids:
                for row_content_id, folder_id, name in session.execute(select(
                    ContentFavoriteFolderRow.content_id, FavoriteFolderRow.id, FavoriteFolderRow.name,
                ).join(FavoriteFolderRow, FavoriteFolderRow.id == ContentFavoriteFolderRow.folder_id).where(
                    ContentFavoriteFolderRow.content_id.in_(selected_ids),
                )).all():
                    add_facet(rows_by_id[row_content_id], "favorite_folder", folder_id, name)
                for row_content_id, tag_id, name in session.execute(select(
                    ContentTagRow.content_id, TagRow.id, TagRow.name,
                ).join(TagRow, TagRow.id == ContentTagRow.tag_id).where(
                    ContentTagRow.content_id.in_(selected_ids), TagRow.user_id == "local",
                )).all():
                    add_facet(rows_by_id[row_content_id], "user_tag", tag_id, name)
                for row_content_id, topic_id, name in session.execute(select(
                    ContentTopicRow.content_id, RagTopicRow.id, RagTopicRow.name,
                ).join(RagTopicRow, RagTopicRow.id == ContentTopicRow.topic_id).where(
                    ContentTopicRow.content_id.in_(selected_ids), ContentTopicRow.status == "confirmed",
                    RagTopicRow.catalog_version == CATALOG_VERSION,
                )).all():
                    add_facet(rows_by_id[row_content_id], "topic", topic_id, name)
                for row_content_id, tag_id, name in session.execute(select(
                    ContentRagDetailTagRow.content_id, RagDetailTagRow.id, RagDetailTagRow.display_name,
                ).join(RagDetailTagRow, RagDetailTagRow.id == ContentRagDetailTagRow.tag_id).where(
                    ContentRagDetailTagRow.content_id.in_(selected_ids),
                    ContentRagDetailTagRow.status == "active", RagDetailTagRow.status == "active",
                )).all():
                    add_facet(rows_by_id[row_content_id], "detail_tag", tag_id, name)

        related_content_ids = []
        if content_id:
            seed_targets = {edge["target"] for edge in edges if edge["source"] == f"content:{content_id}"}
            related_content_ids = list(dict.fromkeys(
                edge["source"].removeprefix("content:") for edge in edges
                if edge["target"] in seed_targets and edge["source"] != f"content:{content_id}"
            ))[:limit]
        content_nodes = [node for node in nodes.values() if node["kind"] == "content"]
        facet_nodes = [node for node in nodes.values() if node["kind"] != "content"]
        relation_kinds = ("favorite", "favorite_folder", "user_tag", "platform", "author",
                          "media_type", "topic", "detail_tag")
        coverage_sources = {kind: {edge["source"] for edge in edges if edge["relation"] == kind}
                            for kind in relation_kinds}
        return {
            "selected_content_id": content_id,
            "nodes": content_nodes + facet_nodes,
            "edges": edges,
            "related_content_ids": related_content_ids,
            "page": {"offset": offset, "limit": limit, "count": len(content_nodes),
                     "total_count": total_count, "has_more": has_more, "truncated": has_more},
            "relation_coverage": {kind: {"content_count": len(coverage_sources[kind]),
                                         "content_total": len(content_nodes)}
                                  for kind in relation_kinds},
        }

    def set_coverage(
        self, content_id: str, *, source_version: str, material_level: str,
        status: str, error_code: str | None = None, trace: dict | None = None,
    ) -> None:
        now = datetime.now(UTC)
        with self.store.session_factory.begin() as session:
            row = session.get(RagCoverageRow, content_id)
            if row is None:
                row = RagCoverageRow(content_id=content_id, source_version=source_version,
                                     material_level=material_level, status=status,
                                     error_code=error_code, trace=dict(trace or {}), updated_at=now)
                session.add(row)
            else:
                row.source_version = source_version
                row.material_level = material_level
                row.status = status
                row.error_code = error_code
                row.trace = dict(trace or row.trace or {})
                row.updated_at = now

    def get_coverage(self, content_id: str) -> dict | None:
        with self.store.session_factory() as session:
            row = session.get(RagCoverageRow, content_id)
            if row is None:
                return None
            return {"content_id": row.content_id, "source_version": row.source_version,
                    "material_level": row.material_level, "status": row.status,
                    "error_code": row.error_code, "trace": row.trace}

    def replace_topics(
        self, content_id: str, *, source_version: str, material_level: str,
        topics: list[dict], source_refs: list[str], coverage_status: str = "complete",
    ) -> None:
        now = datetime.now(UTC)
        if material_level == "M0":
            self.set_coverage(content_id, source_version=source_version,
                              material_level=material_level, status="metadata_only")
            return
        normalized = []
        for item in topics:
            topic_id = str(item["topic_id"])
            validate_topic_ids([topic_id])
            role = item.get("role", "primary")
            discussion = item.get("discussion", "substantive")
            if role not in {"primary", "secondary"} or discussion not in {"substantive", "mention"}:
                raise ValueError("主题关联字段无效")
            refs = list(dict.fromkeys(item.get("source_refs") or source_refs))
            if not refs:
                continue
            normalized.append((topic_id, role, discussion, refs))
        if len(normalized) > 5:
            raise ValueError("每篇至多关联 5 个规范主题")
        with self.store.session_factory.begin() as session:
            session.query(ContentTopicRow).filter_by(content_id=content_id).delete()
            for topic_id, role, discussion, refs in normalized:
                session.add(ContentTopicRow(
                    content_id=content_id, topic_id=topic_id, role=role,
                    discussion=discussion, source_version=source_version,
                    source_refs=refs, status="confirmed", updated_at=now,
                ))
            coverage = session.get(RagCoverageRow, content_id)
            if coverage is None:
                session.add(RagCoverageRow(
                    content_id=content_id, source_version=source_version,
                    material_level=material_level,
                    status=coverage_status if normalized else "no_topics",
                    error_code=None, updated_at=now,
                ))
            else:
                coverage.source_version = source_version
                coverage.material_level = material_level
                coverage.status = coverage_status if normalized else "no_topics"
                coverage.error_code = None
                coverage.updated_at = now

    def reset_content_classification(self, content_id: str, source_version: str) -> None:
        now = datetime.now(UTC)
        with self.store.session_factory.begin() as session:
            session.query(ContentTopicRow).filter_by(content_id=content_id).delete()
            links = session.execute(select(ContentRagDetailTagRow).where(
                ContentRagDetailTagRow.content_id == content_id,
            )).scalars().all()
            for link in links:
                link.status = "invalid"
                link.updated_at = now
            coverage = session.get(RagCoverageRow, content_id)
            if coverage is not None and coverage.source_version != source_version:
                coverage.source_version = source_version
                coverage.status = "pending"
                coverage.error_code = None
                coverage.updated_at = now

    def invalidate_content(self, content_id: str) -> None:
        """Withdraw all internal RAG evidence when a source is deleted."""

        now = datetime.now(UTC)
        with self.store.session_factory.begin() as session:
            session.query(ContentTopicRow).filter_by(content_id=content_id).delete()
            links = session.execute(select(ContentRagDetailTagRow).where(
                ContentRagDetailTagRow.content_id == content_id,
            )).scalars().all()
            for link in links:
                link.status = "invalid"
                link.updated_at = now
            coverage = session.get(RagCoverageRow, content_id)
            if coverage is not None:
                coverage.status = "source_missing"
                coverage.error_code = "source_deleted"
                coverage.updated_at = now

    def upsert_detail_tag(
        self, *, name: str, definition: str, content_id: str,
        topic_ids: list[str], source_refs: list[str], source_version: str,
        extractor_model: str | None = None, prompt_version: str | None = None,
    ) -> dict:
        normalized, definition = validate_detail_tag(name, definition)
        valid_topics = list(validate_topic_ids(topic_ids))
        refs = list(dict.fromkeys(source_refs))
        if not refs:
            raise ValueError("细标签必须带有来源位置")
        now = datetime.now(UTC)
        with self.store.session_factory.begin() as session:
            tag = session.execute(select(RagDetailTagRow).where(
                RagDetailTagRow.normalized_name == normalized,
                RagDetailTagRow.short_definition == definition,
            )).scalar_one_or_none()
            if tag is None:
                tag = RagDetailTagRow(
                    id=new_id("rdtag"), display_name=name.strip(), normalized_name=normalized,
                    short_definition=definition, aliases=[], status="candidate",
                    extractor_model=extractor_model, prompt_version=prompt_version,
                    last_qualified_query_at=None, created_at=now,
                )
                session.add(tag)
                session.flush()
            relation = session.execute(select(ContentRagDetailTagRow).where(
                ContentRagDetailTagRow.content_id == content_id,
                ContentRagDetailTagRow.tag_id == tag.id,
            )).scalar_one_or_none()
            if relation is None:
                relation = ContentRagDetailTagRow(
                    id=new_id("crtag"), content_id=content_id, tag_id=tag.id,
                    topic_ids=valid_topics, source_refs=refs,
                    source_version=source_version, status="candidate", updated_at=now,
                )
                session.add(relation)
            else:
                relation.topic_ids = valid_topics
                relation.source_refs = refs
                relation.source_version = source_version
                relation.status = "active" if tag.status == "active" else "candidate"
                relation.updated_at = now
            return {"id": tag.id, "name": name.strip(), "definition": definition,
                    "status": tag.status, "topic_ids": valid_topics}

    def list_detail_tags(self, *, active_only: bool = False) -> list[dict]:
        with self.store.session_factory() as session:
            statement = select(RagDetailTagRow)
            if active_only:
                statement = statement.where(RagDetailTagRow.status == "active")
            rows = session.execute(statement.order_by(RagDetailTagRow.normalized_name)).scalars().all()
        now = datetime.now(UTC)
        values = [{"id": row.id, "name": row.display_name,
                 "definition": row.short_definition, "aliases": row.aliases,
                 "status": "dormant" if row.status == "active" and row.last_qualified_query_at
                 and _as_utc(row.last_qualified_query_at) < now - timedelta(days=90) else row.status}
                for row in rows]
        return [item for item in values if item["status"] == "active"] if active_only else values

    def record_tag_feedback(self, *, query_id: str, content_id: str, tag_id: str, helpful: bool) -> bool:
        now = datetime.now(UTC)
        with self.store.session_factory.begin() as session:
            existing = session.execute(select(RagFeedbackEventRow).where(
                RagFeedbackEventRow.query_id == query_id,
                RagFeedbackEventRow.content_id == content_id,
                RagFeedbackEventRow.tag_id == tag_id,
            )).scalar_one_or_none()
            if existing is not None:
                return False
            session.add(RagFeedbackEventRow(
                id=new_id("rdfe"), query_id=query_id, content_id=content_id,
                tag_id=tag_id, helpful=helpful, created_at=now,
            ))
            if helpful:
                tag = session.get(RagDetailTagRow, tag_id)
                if tag is not None:
                    tag.last_qualified_query_at = now
        return True

    def feedback_tag_ids(self, content_id: str) -> set[str]:
        with self.store.session_factory() as session:
            rows = session.execute(select(ContentRagDetailTagRow.tag_id).join(
                RagDetailTagRow, RagDetailTagRow.id == ContentRagDetailTagRow.tag_id,
            ).where(
                ContentRagDetailTagRow.content_id == content_id,
                ContentRagDetailTagRow.status.in_(["candidate", "active"]),
                RagDetailTagRow.status.in_(["candidate", "active"]),
            )).scalars().all()
        return set(rows)

    def promote_eligible_tags(self) -> list[str]:
        """Promote only after behavior, source and developer review evidence."""

        cutoff = datetime.now(UTC) - timedelta(days=90)
        with self.store.session_factory.begin() as session:
            rows = session.execute(
                select(RagFeedbackEventRow.tag_id)
                .where(RagFeedbackEventRow.helpful.is_(True), RagFeedbackEventRow.created_at >= cutoff)
                .group_by(RagFeedbackEventRow.tag_id)
                .having(func.count(func.distinct(RagFeedbackEventRow.query_id)) >= 2,
                        func.count(func.distinct(RagFeedbackEventRow.content_id)) >= 2)
            ).scalars().all()
            active_count = session.scalar(select(func.count()).select_from(RagDetailTagRow).where(
                RagDetailTagRow.status == "active")) or 0
            promoted = []
            for tag_id in rows:
                if active_count >= 1000:
                    break
                tag = session.get(RagDetailTagRow, tag_id)
                if tag is None or tag.status not in {"candidate", "active"} or not tag.source_reviewed:
                    continue
                developer_review = session.execute(select(RagDeveloperTagReviewRow).where(
                    RagDeveloperTagReviewRow.tag_id == tag_id,
                ).order_by(RagDeveloperTagReviewRow.created_at.desc()).limit(1)).scalar_one_or_none()
                if developer_review is None or developer_review.decision != "approved":
                    continue
                links = session.execute(select(ContentRagDetailTagRow).where(
                    ContentRagDetailTagRow.tag_id == tag_id,
                    ContentRagDetailTagRow.status == "candidate",
                    ContentRagDetailTagRow.source_refs != [],
                )).scalars().all()
                if not links or tag.status == "active":
                    continue
                tag.status = "active"
                active_count += 1
                promoted.append(tag_id)
                for link in links:
                    link.status = "active"
        return promoted

    def eligible_tag_reviews(self, *, developer_only: bool = False) -> list[dict]:
        cutoff = datetime.now(UTC) - timedelta(days=90)
        with self.store.session_factory() as session:
            tag_ids = session.execute(select(RagFeedbackEventRow.tag_id)
                .where(RagFeedbackEventRow.helpful.is_(True), RagFeedbackEventRow.created_at >= cutoff)
                .group_by(RagFeedbackEventRow.tag_id)
                .having(func.count(func.distinct(RagFeedbackEventRow.query_id)) >= 2,
                        func.count(func.distinct(RagFeedbackEventRow.content_id)) >= 2)
            ).scalars().all()
            tags = session.execute(select(RagDetailTagRow).where(
                RagDetailTagRow.id.in_(tag_ids) if tag_ids else False,
                RagDetailTagRow.status == "candidate",
            )).scalars().all()
            result = []
            for tag in tags:
                if bool(tag.source_reviewed) != developer_only:
                    continue
                links = session.execute(select(ContentRagDetailTagRow).where(
                    ContentRagDetailTagRow.tag_id == tag.id,
                    ContentRagDetailTagRow.status == "candidate",
                )).scalars().all()
                result.append({
                    "id": tag.id, "name": tag.display_name,
                    "definition": tag.short_definition,
                    "source_reviewed": tag.source_reviewed,
                    "contexts": [{"content_id": link.content_id, "source_refs": link.source_refs,
                                  "source_version": link.source_version, "topic_ids": link.topic_ids}
                                 for link in links if link.source_refs],
                })
        return result

    def review_developer_candidate(
        self, tag_id: str, *, decision: str, material_evidence: list[dict], note: str | None = None,
    ) -> dict | None:
        """Record a human decision against current source excerpts and apply it."""

        if decision not in {"approved", "rejected"}:
            raise ValueError("审核决定无效")
        now = datetime.now(UTC)
        with self.store.session_factory.begin() as session:
            tag = session.get(RagDetailTagRow, tag_id)
            if tag is None or tag.status != "candidate" or not tag.source_reviewed:
                return None
            cutoff = now - timedelta(days=90)
            behavior_counts = session.execute(select(
                func.count(func.distinct(RagFeedbackEventRow.query_id)),
                func.count(func.distinct(RagFeedbackEventRow.content_id)),
            ).where(
                RagFeedbackEventRow.tag_id == tag_id,
                RagFeedbackEventRow.helpful.is_(True),
                RagFeedbackEventRow.created_at >= cutoff,
            )).one()
            if behavior_counts[0] < 2 or behavior_counts[1] < 2:
                return None
            links = session.execute(select(ContentRagDetailTagRow).where(
                ContentRagDetailTagRow.tag_id == tag_id,
                ContentRagDetailTagRow.status == "candidate",
            )).scalars().all()
            link_by_content = {link.content_id: link for link in links if link.source_refs}
            evidence = []
            for item in material_evidence:
                content_id = str(item.get("content_id", ""))
                link = link_by_content.get(content_id)
                refs = list(dict.fromkeys(
                    ref for ref in item.get("source_refs", []) if ref in (link.source_refs if link else [])
                ))
                text = str(item.get("text", "")).strip()[:1200]
                if link is None or not refs or item.get("source_version") != link.source_version or not text:
                    continue
                evidence.append({
                    "content_id": content_id,
                    "source_refs": refs[:8],
                    "source_version": link.source_version,
                    "text": text,
                })
            if len({item["content_id"] for item in evidence}) < 2:
                return None

            trace = dict(tag.review_trace or {})
            same_concept = bool(trace.get("same_concept"))
            canonical_tag_id = trace.get("canonical_tag_id") if same_concept else None
            canonical = session.get(RagDetailTagRow, canonical_tag_id) if canonical_tag_id else None
            if decision == "approved" and same_concept and (canonical is None or canonical.status != "active"):
                return None
            session.add(RagDeveloperTagReviewRow(
                id=new_id("rdreview"), tag_id=tag.id, decision=decision,
                reviewer="developer", note=(note or "").strip()[:300] or None,
                candidate_name=tag.display_name, candidate_definition=tag.short_definition,
                same_concept=same_concept, canonical_tag_id=canonical_tag_id,
                material_evidence=evidence[:10], created_at=now,
            ))
            trace["developer_review"] = {"decision": decision, "at": now.isoformat()}
            tag.review_trace = trace
            status = tag.status
            if decision == "approved" and same_concept:
                aliases = trace.get("aliases") or []
                canonical.aliases = list(dict.fromkeys(
                    list(canonical.aliases or []) + [tag.display_name] + list(aliases)
                ))
                tag.status = "merged"
                tag.redirected_to = canonical.id
                for link in links:
                    existing = session.execute(select(ContentRagDetailTagRow).where(
                        ContentRagDetailTagRow.content_id == link.content_id,
                        ContentRagDetailTagRow.tag_id == canonical.id,
                    )).scalar_one_or_none()
                    if existing is None:
                        session.add(ContentRagDetailTagRow(
                            id=new_id("crtag"), content_id=link.content_id, tag_id=canonical.id,
                            topic_ids=link.topic_ids, source_refs=link.source_refs,
                            source_version=link.source_version, status="active", updated_at=now,
                        ))
                    else:
                        existing.source_refs = list(dict.fromkeys(existing.source_refs + link.source_refs))
                    link.status = "merged"
                status = tag.status
        return {"tag_id": tag_id, "decision": decision, "status": status}

    def list_developer_tag_reviews(self, tag_id: str | None = None) -> list[dict]:
        statement = select(RagDeveloperTagReviewRow)
        if tag_id is not None:
            statement = statement.where(RagDeveloperTagReviewRow.tag_id == tag_id)
        statement = statement.order_by(RagDeveloperTagReviewRow.created_at, RagDeveloperTagReviewRow.id)
        with self.store.session_factory() as session:
            rows = session.execute(statement).scalars().all()
        return [{
            "id": row.id, "tag_id": row.tag_id, "decision": row.decision,
            "reviewer": row.reviewer, "note": row.note,
            "candidate_name": row.candidate_name,
            "candidate_definition": row.candidate_definition,
            "same_concept": row.same_concept, "canonical_tag_id": row.canonical_tag_id,
            "material_evidence": row.material_evidence, "created_at": row.created_at,
        } for row in rows]

    def review_tag_candidate(
        self, tag_id: str, *, source_supported: bool, verified_content_ids: list[str],
        same_concept: bool, canonical_tag_id: str | None = None,
        aliases: list[str] | None = None, trace: dict | None = None,
    ) -> bool:
        """Persist a separately checked P-MERGE review; review alone does not merge."""

        now = datetime.now(UTC)
        with self.store.session_factory.begin() as session:
            tag = session.get(RagDetailTagRow, tag_id)
            if tag is None or tag.status != "candidate":
                return False
            links = session.execute(select(ContentRagDetailTagRow).where(
                ContentRagDetailTagRow.tag_id == tag_id,
                ContentRagDetailTagRow.status == "candidate",
            )).scalars().all()
            valid_content_ids = {item.content_id for item in links if item.source_refs}
            verified = set(verified_content_ids) & valid_content_ids
            if not source_supported or len(verified) < 2:
                tag.review_trace = dict(trace or {})
                return False
            if same_concept:
                canonical = session.get(RagDetailTagRow, canonical_tag_id) if canonical_tag_id else None
                if canonical is None or canonical.status != "active":
                    return False
            tag.source_reviewed = True
            tag.review_trace = {
                **dict(trace or {}),
                "source_supported": True,
                "verified_content_ids": sorted(verified),
                "same_concept": same_concept,
                "canonical_tag_id": canonical_tag_id if same_concept else None,
                "aliases": list(dict.fromkeys(aliases or [])) if same_concept else [],
            }
        return True

    def create_session(self, title: str, scope: dict) -> dict:
        now = datetime.now(UTC)
        row = RagSessionRow(id=new_id("ask"), title=title[:200] or "新会话",
                            scope=dict(scope), created_at=now, updated_at=now)
        with self.store.session_factory.begin() as session:
            session.add(row)
        return self.session_dict(row)

    def session_dict(self, row: RagSessionRow) -> dict:
        return {"id": row.id, "title": row.title, "scope": row.scope,
                "created_at": row.created_at, "updated_at": row.updated_at}

    def list_sessions(self, limit: int = 50) -> list[dict]:
        with self.store.session_factory() as session:
            rows = session.execute(select(RagSessionRow).where(
                RagSessionRow.deleted_at.is_(None)).order_by(
                    RagSessionRow.updated_at.desc()).limit(min(100, max(1, limit)))).scalars().all()
        return [self.session_dict(row) for row in rows]

    def get_session(self, session_id: str) -> dict:
        with self.store.session_factory() as session:
            row = session.get(RagSessionRow, session_id)
            if row is None or row.deleted_at is not None:
                raise LookupError(session_id)
            result = self.session_dict(row)
            queries = session.execute(select(RagQueryRow).where(
                RagQueryRow.session_id == session_id).order_by(RagQueryRow.created_at)).scalars().all()
            result["messages"] = [self.query_dict(query) for query in queries]
        return result

    def create_query(self, session_id: str, question: str, scope: dict) -> dict:
        now = datetime.now(UTC)
        row = RagQueryRow(id=new_id("aq"), session_id=session_id, question=question,
                          scope_snapshot=dict(scope), status="queued", result=None, trace={},
                          cancel_requested=False, created_at=now, updated_at=now)
        with self.store.session_factory.begin() as session:
            parent = session.get(RagSessionRow, session_id)
            if parent is None or parent.deleted_at is not None:
                raise LookupError(session_id)
            session.add(row)
            parent.updated_at = now
            if parent.title == "新会话":
                parent.title = question[:80]
        return self.query_dict(row)

    def query_dict(self, row: RagQueryRow) -> dict:
        return {"id": row.id, "session_id": row.session_id, "question": row.question,
                "status": row.status, "result": row.result, "trace": row.trace,
                "scope": row.scope_snapshot, "created_at": row.created_at,
                "updated_at": row.updated_at}

    def get_query(self, query_id: str) -> dict:
        with self.store.session_factory() as session:
            row = session.get(RagQueryRow, query_id)
            if row is None:
                raise LookupError(query_id)
            return self.query_dict(row)

    def update_query(self, query_id: str, *, status: str | None = None,
                     result: dict | None = None, trace: dict | None = None,
                     scope: dict | None = None) -> None:
        with self.store.session_factory.begin() as session:
            row = session.get(RagQueryRow, query_id)
            if row is None:
                raise LookupError(query_id)
            if row.cancel_requested and status != "cancelled":
                row.status = "cancelled"
                row.updated_at = datetime.now(UTC)
                return
            if status is not None:
                row.status = status
            if result is not None:
                row.result = result
            if trace is not None:
                row.trace = trace
            if scope is not None:
                row.scope_snapshot = dict(scope)
            row.updated_at = datetime.now(UTC)

    def resume_query(self, query_id: str) -> None:
        with self.store.session_factory.begin() as session:
            row = session.get(RagQueryRow, query_id)
            if row is None:
                raise LookupError(query_id)
            if row.status not in {"paused", "failed"}:
                raise ValueError("只有暂停或失败的问答任务可以继续")
            row.cancel_requested = False
            row.status = "queued"
            row.trace = {**(row.trace or {}), "refresh_scope_on_resume": True}
            row.updated_at = datetime.now(UTC)

    def record_answer_feedback(self, query_id: str, helpful: bool, note: str | None = None) -> bool:
        now = datetime.now(UTC)
        with self.store.session_factory.begin() as session:
            existing = session.execute(select(RagAnswerFeedbackRow).where(
                RagAnswerFeedbackRow.query_id == query_id)).scalar_one_or_none()
            if existing is not None:
                return False
            session.add(RagAnswerFeedbackRow(id=new_id("af"), query_id=query_id,
                helpful=helpful, note=note.strip()[:500] if note else None, created_at=now))
        return True

    def request_cancel(self, query_id: str) -> None:
        with self.store.session_factory.begin() as session:
            row = session.get(RagQueryRow, query_id)
            if row is None:
                raise LookupError(query_id)
            row.cancel_requested = True
            if row.status in {"queued", "running"}:
                row.status = "cancelling"
            row.updated_at = datetime.now(UTC)

    def delete_session(self, session_id: str) -> None:
        with self.store.session_factory.begin() as session:
            row = session.get(RagSessionRow, session_id)
            if row is None:
                raise LookupError(session_id)
            row.deleted_at = datetime.now(UTC)
            row.updated_at = row.deleted_at
            queries = session.execute(select(RagQueryRow).where(
                RagQueryRow.session_id == session_id,
                RagQueryRow.status.in_(["queued", "running", "cancelling"]),
            )).scalars().all()
            for query in queries:
                query.cancel_requested = True
                query.status = "cancelling"
                query.updated_at = row.updated_at

    def upsert_scan_item(self, *, query_id: str, content_id: str, source_version: str,
                         cursor: str | None, decision: str, evidence_refs: list[str],
                         completed: bool, error_code: str | None = None) -> None:
        now = datetime.now(UTC)
        with self.store.session_factory.begin() as session:
            row = session.execute(select(RagScanItemRow).where(
                RagScanItemRow.query_id == query_id,
                RagScanItemRow.content_id == content_id,
            )).scalar_one_or_none()
            if row is None:
                row = RagScanItemRow(id=new_id("scan"), query_id=query_id,
                                     content_id=content_id, source_version=source_version,
                                     cursor=cursor, decision=decision,
                                     evidence_refs=evidence_refs, completed=completed,
                                     error_code=error_code, updated_at=now)
                session.add(row)
            elif row.source_version != source_version:
                row.source_version = source_version
                row.cursor = cursor
                row.decision = decision
                row.evidence_refs = evidence_refs
                row.completed = completed
                row.error_code = error_code
                row.updated_at = now
            else:
                row.cursor = cursor
                row.decision = decision
                row.evidence_refs = evidence_refs
                row.completed = completed
                row.error_code = error_code
                row.updated_at = now

    def list_scan_items(self, query_id: str) -> list[dict]:
        with self.store.session_factory() as session:
            rows = session.execute(select(RagScanItemRow).where(
                RagScanItemRow.query_id == query_id).order_by(RagScanItemRow.content_id)).scalars().all()
        return [{"content_id": row.content_id, "source_version": row.source_version,
                 "cursor": row.cursor, "decision": row.decision,
                 "evidence_refs": row.evidence_refs, "completed": row.completed,
                 "error_code": row.error_code} for row in rows]


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
