# 统一任务记录与事件关联

借鉴 DeepSeek Super-agent 的任务组织方式，为已有学习工作流补充持久任务编号、状态索引与显式事件关联。它是本工作流的独立实现，没有安装或复用 DeepSeek 原型代码，也不要求更换模型。

## 优先级与实施范围

| 优先级 | 工作 | 当前实现与验收 |
|---|---|---|
| P0 | 稳定任务编号、持久任务与事件记录 | SQLite事务、事件幂等与冲突拒绝、修改版本检查；重启后保留关联 |
| P1 | 关联现有入口、汇总待办 | 只读接入媒体队列和Hermes协作消息；显式关联原任务；沿用原一分钟同步可选刷新 |
| P2 | 检查停滞与有限恢复 | 已有只读异常观察；自动恢复、实验日志和PR适配尚未实现，媒体恢复仍由原队列执行 |
| P3 | 长期调度多个Worker | 尚未实现；需先明确任务执行范围、隔离目录、并发与取消机制、执行回执及运行环境 |

先保证任务能追溯和恢复，再扩展执行。入口、消息与媒体身份继续沿用原编号，新任务编号由来源及原编号确定。Hermes消息内容只作为资料；来源关联不会产生执行授权。

## 使用

以下在工作流脚本所在目录运行，`ROOT`替换为自己的私人工作流根目录：

```sh
python3 task_center.py --root ROOT preview
python3 task_center.py --root ROOT sync
python3 task_center.py --root ROOT status
python3 task_center.py --root ROOT attention
```

`preview`只读取源记录，不创建索引；`sync`更新本地任务索引，不调用网络、模型或原队列的认领/重试操作。`status`给出全部任务与待关联事件；`attention`重点显示受阻、传输待处理、源文件缺失等需核对的事项。它是按需查看入口，没有新增通知服务。

媒体投影状态以原媒体JSON为准，不能用任务中枢CLI手工修改。`delivered`显示“结果已送达，待读取/核对”，不代表Hermes已读、本人掌握或需要逐条本人批准。`partial_ready`保留覆盖缺口提示，不默认变成强制人工待办。源记录缺失或校验失败时，显示待核对，不能用缓存证明仍在正常推进。

独立工作可以手工登记，后续事件明确关联到它：

```sh
python3 task_center.py --root ROOT create --key my-task --title 一项真实任务 --next-action 核对原始结果
python3 task_center.py --root ROOT link --event EVENT_ID --task TASK_ID
python3 task_center.py --root ROOT events --task TASK_ID
python3 task_center.py --root ROOT set-status --task TASK_ID --revision REVISION --status completed --evidence EVIDENCE_PATH
```

请使用实际返回的编号与revision。`completed`要求提供非空证据引用；程序不据此判断证据内容正确，也不产生“本人已掌握”状态。测试事件和真实任务不可交叉关联。关联不可悄悄转移到另一任务。同编号事件内容变化时，`sync` 在 `observations` 中标出 `immutable_event_conflict`，保留旧事件及关联，并继续索引其他记录。

事件只保存原件引用、主题、类型和哈希，不复制消息正文。未关联事件保留待分流，不按标题相似度猜测归属。现阶段关联保存在本机，没有自动把消息投递到执行会话，也没有跨设备同步任务数据库。

## 复用现有同步

确认模块已完整安装后，可在私人ROOT新增`task_center.local.json`：

```json
{"enabled": true}
```

现有Codex角色的`collaboration_flow.py tick`会在收件、协作与媒体发现之后刷新索引。无需新建定时任务。未配置或`enabled=false`时保持原行为；Hermes角色不运行此索引。索引异常单独记为`task_center`错误，不跳过原有收件和协作交换；观察到媒体受阻本身不算传输失败。

SQLite位于`ROOT/任务中枢/state.sqlite3`，只保存本机状态，不上传团队库。停用时设`enabled=false`，保留数据库和源记录。Mac休眠或离线时不能即时刷新，恢复后下一次既有同步补查；不能承诺持续在线。

安装时同时复制[命令入口](../scripts/task_center.py)、[任务模块目录](../scripts/任务中枢)、更新后的[协作脚本](../scripts/collaboration_flow.py)，并保留原`learning_flow.py`与`media_queue.py`。本机配置不进发行包。

## 验证

```sh
python3 -m unittest discover -s 任务中枢 -p 'test_task_*.py' -v
```

在脚本目录执行；测试使用临时目录，覆盖事件重复与冲突、源状态跟随、源文件字节不变、测试隔离、显式关联与重启、缺失源处理、可选tick成功/禁用/失败。自动化测试不代替真人微信后续意见→原任务→实际处理结果的端到端验收。

设计参考：[DeepSeek官方研究原型](https://github.com/deepseek-ai/dsh-superagent-prototype)、[领域模型](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/main/docs/001-domain.md)。该项目自身也明确区分研究原型和正式产品；本功能只借鉴组织方法。
