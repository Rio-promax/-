# 非视频总结 Prompt 分流

用户已于2026-11-09明确要求代码修改。范围：复用ContentKind；文章/图片文字/PDF使用已确认的非视频Prompt，删除“时间戳或来源位置”一句；视频沿用当前Prompt。音频不在本轮文字入口范围，保持既有行为。不修改ASR、embedding、索引切片、UI或分类体系。

非视频Prompt的重要原则为总结篇幅不得超过原始文字篇幅；本轮落实为模型指令，不新增硬截断/重复调用。材料包装使用内容标题、文字材料及段落，不向文字输入附媒体时间。总结强度、风格和Skill保持现有传递。

默认Prompt按内容类型在submit时选择，冻结实际Prompt、哈希和版本。用户显式自定义Prompt继续尊重，不覆盖；已有任务快照不回写。验证真实请求载荷、持久化快照和视频回归。API重试仍按现有创建新任务配置处理。

代码入口：knowledge/prompts.py、workflows/analyze.py、adapters/summary/openai_compatible.py。验证：test_text_summary_prompt.py及总结相关回归。Git main/bc6efed，起始工作树干净。

## 进度现状与任务记录

| 项 | 自动验证是否通过 | 人工验证是否通过 |
|---|---|---|
| R1 非视频Prompt与快照 | 通过（请求/快照及回归） | |
| R2 文字材料包装与视频回归 | 通过（请求/快照及回归） | |

红灯：新增请求载荷测试3失败（article/image/pdf仍使用视频Prompt）、video通过。模型实际输出的长度和语义效果待人工验收。


自动验证：在main/bc6efed后的本轮dirty代码执行：

```powershell
product/.venv/Scripts/python.exe -m pytest product/src/services/core/tests/test_text_summary_prompt.py product/src/services/core/tests/test_summary_integration.py product/src/services/core/tests/test_summary_styles.py product/src/services/core/tests/test_local_workflow.py product/src/services/core/tests/test_link_import.py product/src/services/core/tests/test_summary_product.py -q -k 'not test_summary_key_only_put_saves_after_matching_validation and not test_summary_ui_auto_discovers_models_and_validates_before_saving' --basetemp=product/local/pytest-text-summary-verified-1109
```

结果166通过、2排除、1条Starlette/httpx弃用警告。新增9项覆盖两种API格式、article/image/pdf/video请求载荷及显式自定义Prompt保留；已有归档/重总结/强度与风格回归通过。git diff --check通过。

完整选集曾因2项既有测试失败：summary_key_only_put_saves_after_matching_validation（SQLAlchemy结果读取IndexError）；summary_ui_auto_discovers_models_and_validates_before_saving（旧UI文案断言）。以git show HEAD加载本轮3份生产文件的原始实现，在独立进程重跑这两项，同样2失败；本轮不修改设置/UI。默认Windows临时目录曾出现归档rename拒绝，改项目内basetemp后受影响归档测试通过。

未调用真实外部模型，未重启/部署运行服务。篇幅限制仅为Prompt原则，不宣称模型必然遵守；短句/链接/长文章效果待人工验收。没有截断生成文本、添加分类标签或改动embedding。
