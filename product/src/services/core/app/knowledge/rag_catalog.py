"""Versioned controlled vocabulary for RAG classification and retrieval tags."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

CATALOG_VERSION = "2026-10-31"


@dataclass(frozen=True, slots=True)
class Topic:
    id: str
    name: str
    description: str


TOPICS = (
    Topic("T01", "影视综艺", "电影、剧集、综艺、剧情短片及相关评论、剪辑"),
    Topic("T02", "明星娱乐", "艺人动态、粉丝活动及娱乐行业内容"),
    Topic("T03", "音乐", "歌曲、演奏、音乐创作、乐理、乐评及音乐教学"),
    Topic("T04", "舞蹈", "舞蹈表演、编舞及舞蹈教学"),
    Topic("T05", "动漫文化", "动画、漫画、角色及二次元文化"),
    Topic("T06", "绘画创作", "绘画技法、创作过程、作品及绘画材料"),
    Topic("T07", "游戏", "游戏作品、玩法、实况、攻略和电竞"),
    Topic("T08", "幽默搞笑", "段子、恶搞、鬼畜及以幽默为中心的二创"),
    Topic("T09", "新闻时事", "近期公共事件、社会新闻及相关报道解读"),
    Topic("T10", "科学科普", "自然科学、科学原理、实验及研究解释"),
    Topic("T11", "教育学习", "课程教学、应试、语言学习及学习方法"),
    Topic("T12", "人文历史", "历史、文学、文化、哲学等人文内容"),
    Topic("T13", "商业财经", "商业经营、行业经济、金融和投资知识"),
    Topic("T14", "职业发展", "求职面试、职业技能、职场沟通和职业路径"),
    Topic("T15", "人工智能", "AI 模型、应用、技术、行业及影响"),
    Topic("T16", "科技数码", "软件应用、编程、电子设备、工程技术及产品测评"),
    Topic("T17", "汽车交通", "汽车选购、用车养护、车辆技术、公共交通及交通工具"),
    Topic("T18", "服饰穿搭", "服装、鞋包、配饰、搭配及相关时尚内容"),
    Topic("T19", "美妆护肤", "化妆、护肤、美容产品及体验"),
    Topic("T20", "家居家装", "住房、装修、家具、家电和收纳"),
    Topic("T21", "美食餐饮", "烹饪、烘焙、食物、探店及餐饮体验"),
    Topic("T22", "旅行户外", "目的地、旅行攻略、露营、徒步及户外体验"),
    Topic("T23", "运动健身", "体育项目、比赛、运动实践及训练"),
    Topic("T24", "手工制作", "手作、DIY、工艺及制作过程"),
    Topic("T25", "农业乡村", "农业种养、渔业、农事及乡村生产生活"),
    Topic("T26", "动物宠物", "宠物饲养、动物行为及动物观察"),
    Topic("T27", "亲子育儿", "孕产、儿童照护、亲子互动和家庭教育"),
    Topic("T28", "医疗健康", "疾病、医疗、人体健康及心理健康知识"),
    Topic("T29", "情感关系", "恋爱、家庭、人际交往及关系经历"),
    Topic("T30", "摄影摄像", "拍摄技法、影像创作、器材运用和后期"),
    Topic("T31", "收藏潮玩", "模型、手办、玩具、文玩及收藏"),
    Topic("T32", "Vlog", "个人经历、日常生活或活动过程记录"),
)

TOPIC_BY_ID = {topic.id: topic for topic in TOPICS}
TOPIC_BY_NAME = {topic.name: topic for topic in TOPICS}


def normalize_detail_tag(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold().strip()
    return re.sub(r"[\W_]+", "", value, flags=re.UNICODE)


def validate_detail_tag(name: str, definition: str) -> tuple[str, str]:
    name = unicodedata.normalize("NFKC", name).strip()
    definition = unicodedata.normalize("NFKC", definition).strip()
    if not 1 <= len(name) <= 16:
        raise ValueError("细标签名称须为 1 至 16 字符")
    if len(definition) > 40:
        raise ValueError("细标签定义不能超过 40 字符")
    normalized = normalize_detail_tag(name)
    if not normalized or not definition:
        raise ValueError("细标签名称和定义不能为空")
    return normalized, definition


def validate_topic_ids(topic_ids: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    normalized = tuple(dict.fromkeys(topic_ids))
    if len(normalized) > 5 or any(topic_id not in TOPIC_BY_ID for topic_id in normalized):
        raise ValueError("规范主题 ID 无效")
    return normalized


def lexical_candidates(name: str, active_names: list[str], *, limit: int = 5) -> tuple[str, ...]:
    """Return only lexical review candidates; similarity never implies a merge."""

    query = normalize_detail_tag(name)
    if not query:
        return ()
    candidates = []
    for candidate in active_names:
        normalized = normalize_detail_tag(candidate)
        if normalized == query:
            continue
        if query in normalized or normalized in query or _bigram_overlap(query, normalized) >= 0.5:
            candidates.append(candidate)
    candidates.sort(key=lambda item: (-_bigram_overlap(query, normalize_detail_tag(item)), item))
    return tuple(candidates[: min(5, max(0, limit))])


def _bigram_overlap(left: str, right: str) -> float:
    left_pairs = {left[index : index + 2] for index in range(max(1, len(left) - 1))}
    right_pairs = {right[index : index + 2] for index in range(max(1, len(right) - 1))}
    union = left_pairs | right_pairs
    return len(left_pairs & right_pairs) / len(union) if union else float(left == right)
