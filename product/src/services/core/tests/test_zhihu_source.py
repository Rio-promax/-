from app.adapters.sources.zhihu import prepare_zhihu_text
from app.domain.models import ContentKind, SourcePlatform


def test_prepare_zhihu_text_keeps_answer_metadata_and_body() -> None:
    url = "https://www.zhihu.com/question/123/answer/456"

    source = prepare_zhihu_text(
        url=url,
        title="测试回答",
        author="测试作者",
        text="正文第一段。\n\n正文第二段。",
        language="zh-CN",
    )

    assert source.kind is ContentKind.ARTICLE
    assert source.platform is SourcePlatform.ZHIHU
    assert source.source_url == url
    assert source.title == "测试回答"
    assert source.author == "测试作者"
    assert "正文第一段。" in "\n".join(segment.text for segment in source.transcript.segments)


def test_prepare_zhihu_text_rejects_collection_or_other_platform_url() -> None:
    try:
        prepare_zhihu_text(
            url="https://www.zhihu.com/collections",
            title="收藏夹",
            author=None,
            text="不应作为文章提交。",
            language=None,
        )
    except ValueError:
        return
    raise AssertionError("collection pages must not be accepted as article content")
