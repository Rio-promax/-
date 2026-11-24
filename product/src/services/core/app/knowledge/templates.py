"""Built-in summary templates selected per analysis run."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SummaryTemplate:
    id: str
    label: str
    instructions: str


DEFAULT_SUMMARY_TEMPLATE = "general"
SUMMARY_TEMPLATES = {
    "general": SummaryTemplate(
        "general",
        "通用知识总结",
        "按主题、论点、事实和结论组织内容，保留必要的上下文。",
    ),
    "course_notes": SummaryTemplate(
        "course_notes",
        "课程笔记",
        "突出学习目标、核心概念、步骤、例题和课后行动，适合复习。",
    ),
    "meeting_minutes": SummaryTemplate(
        "meeting_minutes",
        "会议纪要",
        "突出议题、共识、分歧、决定、负责人和待办事项；没有明确负责人时不要猜测。",
    ),
    "interview_outline": SummaryTemplate(
        "interview_outline",
        "访谈提纲",
        "按问题、回答要点、人物观点和可追问方向组织，区分受访者原话与整理出的概括。",
    ),
    "opinion_summary": SummaryTemplate(
        "opinion_summary",
        "观点摘要",
        "突出主张、论据、假设、反例和结论，区分事实陈述与观点判断。",
    ),
}


def get_summary_template(template_id: str | None) -> SummaryTemplate:
    value = (template_id or DEFAULT_SUMMARY_TEMPLATE).strip()
    try:
        return SUMMARY_TEMPLATES[value]
    except KeyError as error:
        raise ValueError(f"不支持的总结模板：{value}") from error

# Full summaries use one expression style; local summaries may keep a section template.
SUMMARY_STYLES = {
    "general": ("通用", "按内容本身组织结构，清晰呈现主要信息及其联系，保持表达自然，不强行套用材料不适合的章节。"),
    "course_notes": ("课程笔记", "按课程讲解脉络整理学习目标、概念定义、原理关系、推导过程与例题，突出知识间联系和复习要点；仅在材料提供时归纳练习或课后任务，不补写未讲授的内容。"),
    "academic": ("学术", "采用正式、严谨的表达，清楚区分概念、论点、依据与结论，保留研究条件和局限，不将推测写成定论。"),
    "tutorial": ("教程", "按操作顺序逐步讲解，说明必要准备、关键步骤和完成条件，保留重要参数与注意事项，缺失步骤明确指出。"),
    "sharing": ("分享", "自然呈现材料中的经历、做法与收获，保留适用情境和局限，区分个人体验与事实，不虚构经历或添加营销话术。"),
    "task_oriented": ("任务导向", "围绕目标整理行动、执行顺序及完成条件，突出材料中的优先级和依赖；负责人、期限等信息仅在材料明确时保留。"),
    "business": ("商业风格", "采用正式、精准的表达，围绕业务问题整理事实、分析、影响与建议，保留关键数据、约束和风险，区分事实与判断。"),
    "meeting_minutes": ("会议纪要", "按议题整理讨论要点、明确决定和待办事项，保留已说明的负责人、期限与未决问题，不将讨论意见写成已达成共识。"),
}


def get_summary_style(style_id: str | None) -> tuple[str, str]:
    value = style_id or "general"
    try:
        return SUMMARY_STYLES[value]
    except KeyError as error:
        raise ValueError(f"不支持的表达风格：{value}") from error
