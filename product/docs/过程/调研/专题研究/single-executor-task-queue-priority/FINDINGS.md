---
topic: single-executor-task-queue-priority
created: 2026-09-11
last_verified: 2026-09-12
status: active
depth: deep
related: []
sources:
  - url: https://linear.app/docs/priority
    fetched: 2026-09-11
  - url: https://linear.app/docs/display-options
    fetched: 2026-09-11
  - url: https://linear.app/docs/select-issues
    fetched: 2026-09-11
  - url: https://help.asana.com/s/article/how-to-drag-and-drop-tasks?language=en_US
    fetched: 2026-09-11
  - url: https://help.clickup.com/hc/en-us/articles/6304483666199-Set-task-Priorities
    fetched: 2026-09-11
  - url: https://support.atlassian.com/jira-software-cloud/docs/rank-an-issue/
    fetched: 2026-09-11
  - url: https://www.todoist.com/help/todoist/features/default-sorting-order-in-todoist-mqmgerY7
    fetched: 2026-09-11
  - url: https://support.microsoft.com/en-gb/office/move-tasks-between-or-within-lists-8360617e-63c6-4bf7-952a-60af4b920b62
    fetched: 2026-09-11
  - url: https://www.w3.org/WAI/WCAG22/Understanding/dragging-movements.html
    fetched: 2026-09-11
  - url: https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-cancellation
    fetched: 2026-09-12
  - url: https://docs.celeryq.dev/en/stable/userguide/workers.html
    fetched: 2026-09-12
  - url: https://docs.docker.com/reference/cli/docker/container/pause/
    fetched: 2026-09-12
  - url: https://github.com/hardbyte/awa
    fetched: 2026-09-12
---

# 单执行器任务队列优先级

## Summary

采用“业务优先级”与“执行队列顺序”双轨：优先级是任务属性，拖动只改变单一执行器的队列顺序。

运行中的任务独立置顶。将其后移不是普通排序，而是“保存检查点后暂停并重新入队”。已保存内容、阶段产物及执行日志永久保留；可恢复时从检查点继续，否则另开执行尝试从头运行。

## Findings

成熟产品把优先级等级、手动顺序、状态流转分开。Linear 同时提供优先级属性和共享的手动顺序；Jira 的拖动更新当前列或泳道内的相对 rank。Todoist 和 Microsoft To Do 均将自动排序与手动排序互斥。

本产品应保留“紧急／高／普通／低”作为业务优先级，另增 `queueRank` 表达执行次序。任务卡显示“队列第 N 位／下一个执行”；拖动不默认改变业务优先级。

界面分为“正在执行（1）”“等待执行”“已完成／失败／取消”三个区块。仅等待队列允许自由重排；用专用拖拽手柄、插入线及“已调整为队列第 N 位”反馈。提供上移、下移、置顶、置底和键盘替代操作。自动排序、筛选或分组视图禁用拖动，并提示切换到执行队列。

运行任务被后移时，显示轻量确认：“保存后暂停并重新排队（推荐）”或“继续当前任务，仅调整后续队列”。前者在当前步骤结束或检查点成功写入后，状态从 `running` 经 `pausing` 变为 `queued` 并写入新 rank；在确认前不得启动下一任务。无可靠检查点的任务只能在阶段结束后重排；强制终止须警告可能丢失未保存阶段数据。

任务定义、执行尝试和保存产物分离保存。`task` 保存状态、业务优先级、队列 rank 与版本；`execution_attempt` 保存每次运行的 worker、阶段和检查点；`checkpoint/artifact` 追加保存阶段输出、内容库记录 ID 与时间。重新入队只改状态和 rank，不覆盖任何已保存产物。

用户点击“暂停”后，应把“控制指令已接受”和“执行器已经完全静止”拆成两个状态。界面在一次交互帧内进入 `pausing` 或顶层“已暂停（后台保存中）”，禁止重复点击并给出明确反馈；执行器停止提交新阶段结果、异步保存最近检查点，并在 5 秒内完成让出或进入超时恢复。GitHub Actions 也采用先发送协作式中断、超时后升级终止的分层策略；Celery 则明确提醒，直接终止正在工作的进程属于最后手段，且可能误杀已经接手其他任务的进程。

单执行器不能仅凭前端把旧任务挪到等待区就启动下一任务。若等待区有任务，执行区先显示“正在切换任务”，只有旧执行尝试已静止或其租约被可靠撤销后，才把第一顺位标为真正运行。每次执行使用 attempt/generation token；暂停后的旧 worker 即使迟到返回，也不得写入进度、完成态或产物。Awa 的公开实现同样让运行中取消保持协作式，并使迟到的完成/重试结果成为无操作。

若等待区为空，可立即把顶层状态显示为已暂停，后台保存作为子状态，不占用新的执行槽；恢复必须等待同一检查点保存完成，或明确从上一个已持久化检查点恢复。若 5 秒仍未让出，界面不得一直停在“保存进度”，应显示“暂停超时，正在恢复”，并保持写入隔离。当前若任务直接跑在同一进程/线程且外部调用不可取消，就无法同时保证硬性 5 秒静止和安全续跑；要兑现硬上限，需要把可阻塞阶段放入可回收的子进程或为外部调用增加取消、超时和检查点。

状态机：`queued → claimed → running → pausing → queued`，以及 `running → succeeded / failed / cancelled`。按知识库或执行器范围建立单一活动槽位，限制 `claimed/running/pausing` 至多一条。调度器在事务中认领 rank 最小的 queued 任务；执行器确认后才进入 running。

重排接口提交 `taskId`、前后锚点、`expectedQueueRevision` 和 `idempotencyKey`，而非整个列表。服务端事务内计算稀疏 rank、递增队列版本；间隔耗尽时仅对该队列重编号。并发冲突时按仍存在的锚点落位并返回最新顺序；撤销也是新的重排命令。

## Insights

- 双轨模型避免把“仅调整下一件事”误解为“改变紧急程度”或“立即中断当前工作”。
- 单执行器的关键是服务端原子占有活动槽位，而不是前端只显示一张运行卡。
- 将运行任务独立展示，使后移成为明确的调度操作，能避免用户误把昂贵中断当作纯视觉排序。
- 即时反馈不等于立即释放执行槽；两者分离后，既能符合用户预期，也不破坏单执行器约束。
- 5 秒上限必须对应一个可观测结果：正常让出、升级终止或进入恢复态，不能只是前端倒计时。
- attempt/generation token 是防止暂停后旧 worker 迟到写回、覆盖新任务状态的关键隔离措施。
- 对小型单队列，局部稀疏 rank 和必要时重编号足够；不必复制 Jira 完整的 LexoRank 复杂度。

## Strongest objection

“界面立即显示暂停并马上启动下一任务”可能制造假暂停：旧 worker 仍占 CPU、网络或继续写库，新旧任务会在单执行器中并发。若任务没有可靠检查点或隔离的子进程，强制中断还会丢失未保存阶段数据。因而必须用执行租约/代际令牌阻断迟到写回，并在旧执行真正静止或被可靠隔离后再授予下一任务执行槽。

## Discarded approaches

| Approach | Why dropped | Date |
|---|---|---|

## Open questions

- 当前执行器是否支持阶段级检查点、暂停与恢复；这决定运行中任务能否即时后移。
- 队列是按用户、知识库还是全局共享，决定活动槽位与权限范围。
- 下载、ASR、模型总结三个阻塞阶段分别能否取消；不能取消的阶段是否允许迁移到独立子进程。
- 5 秒超时后产品选择“丢弃未保存进度并强停”还是“保持暂停中并要求用户处理”。

## Timeline

- 2026-09-11 - initial entry
- 2026-09-12 - merged research on immediate pause feedback, five-second yield deadline, cancellation escalation, and stale-worker fencing
