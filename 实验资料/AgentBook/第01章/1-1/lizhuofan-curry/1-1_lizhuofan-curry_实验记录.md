> 记录归属：李卓凡 / `lizhuofan-curry`。原文件：`第一章/1.1上下文消融/实验记录.md`。
> 来源项目提交：`162191203b31ee701f66a1b55b334915f31626e0`；原文SHA-256：`3a64fb8b430b8f8fef2490198d3a25003ffebfec8391f4cabaf88c51b263419a`。
> 2026-10-28导入已有记录，保留正文、真实运行/离线/参考/计划的原有区分；仅增加归档说明并调整必要相对链接，不代表本次重新运行。附件按本人目录隔离。

# 实验1-1记录

## 分步学习进度

2026-10-05，用户真实运行01本地计算器：输入字符串(125 + 375) * 8，返回字典包含expression、result=4000、type=int；通过tool_result["result"]取出4000。无模型API调用，本地工具运行成功，不代表消融实验已完成。

02的Kimi版已于2026-10-06真实运行：第1次请求因账号并发上限返回HTTP 429，等待后重新运行成功。finish_reason=tool_calls，调用ID为calculate_0_6ec3138e，工具名calculate，参数为`{"expression":"(125 + 375) * 8"}`；只提出调用，未执行工具。记录保存在`运行结果/kimi_calculator_request.json`。

因成本考虑，后续实验1.1切换为DeepSeek。Kimi脚本与运行记录保留作对照。DeepSeek版02于2026-10-06真实运行：模型为deepseek-flash，finish_reason=tool_calls，调用ID为call_00_azQxpqV3QZO78Y1XkwZe2063，工具名calculate，参数为`{"expression": "(125 + 375) * 8"}`。记录中calculator_executed=False，并保留后续工具请求需要回传的reasoning_content；未打印推理内容。

03已于2026-10-06真实运行：读取02调用，以相同ID执行本地calculate，得到result=4000；向DeepSeek发送4条消息，第2轮finish_reason=stop、无新工具调用，最终回答为4000，answer_complete=True。记录保存在`运行结果/deepseek_calculator_reply.json`。

用户希望加快学习节奏。04已于2026-10-06真实运行：第1轮发送2条消息，提出1个calculate调用并由Python得到6000；第2轮发送4条消息，finish_reason=stop。最终status=answered、answer_complete=True，记录包含2轮、5条最终历史消息、1次工具行动，保存在`运行结果/deepseek_full_loop.json`。

05的full基线已于2026-10-06真实运行，模型为deepseek-flash。共4轮真实API响应，发送消息数2→6→8→10；先执行3次换汇，再分别计算总收入和季度平均，共5次工具行动且无重复。最终status=answered、completed=True、task_success=True，答案为9602895.73美元和2400723.93美元。已核对每轮响应ID、工具定义、后续历史与reasoning_content均实际存在，full上下文契约通过。证据保存在`运行结果/上下文消融/20261006_101147/evidence.json`。

DeepSeek当前思考模式要求在后续工具请求中保留reasoning_content，与no_reasoning消融定义冲突；05只提供其余4种可实现模式并在证据中标记不是官方精确五组，不把协议不兼容或混用模型当作有效实验结果。

其余3组已于2026-10-06一次运行完成，证据保存在`运行结果/上下文消融/20261006_101914/evidence.json`。已核对每轮均有真实响应ID：no_history的每次请求都只有system和user两条消息；no_tool_calls的请求中没有tools字段；no_tool_results保留工具定义和assistant的tool_calls，但请求中的16条tool消息内容全部为空。

## 正式消融实验（DeepSeek兼容四组已完成）

运行日期：2026-10-06
提供商和实际模型：DeepSeek / deepseek-flash
任务版本：guarded
工具结果隐藏方式：empty
最大迭代次数：5
输出目录：`运行结果/上下文消融/20261006_101147`和`运行结果/上下文消融/20261006_101914`

| 模式 | 有API响应 | 上下文检查通过 | 迭代数 | 工具调用数 | 重复调用 | 数值正确 | 数字有观测依据 | 实际现象 |
|---|---|---|---|---|---|---|---|---|
| full | 是 | 是 | 4 | 5 | 否 | 是 | 是 | 3次换汇后计算总额与平均值，stop结束 |
| no_tool_calls | 是 | 是 | 1 | 0 | 否 | 否 | 不适用（未给数字） | 看不到工具定义，拒绝估算汇率并停止 |
| no_reasoning | 未运行 | 不适用 | — | — | — | — | — | DeepSeek工具协议要求保留reasoning_content，无法做等价消融 |
| no_history | 是 | 是 | 5 | 15 | 是，重复12次 | 否 | 不适用（无最终答案） | 每轮忘记既有调用和结果，重复3次换汇直到达到轮数上限 |
| no_tool_results | 是 | 是 | 4 | 7 | 是，重复4次 | 否 | 不适用（未给数字） | 记得调用历史但观察为空，重试后拒绝给出无依据数字 |

## 一轮执行

用户任务：把四个季度的不同币种收入换算为美元，再计算全年总收入和季度平均收入。

模型提出的工具调用和参数：先并行调用3次convert_currency，参数分别是EUR、GBP、JPY到USD。

程序执行后的真实返回值：2282608.70美元、2278481.01美元、2541806.02美元。

下一次请求中模型实际看见的消息：system、user、带tool_calls的assistant消息，以及3条带真实结果的tool消息。

模型下一步行动：调用calculate求和，再调用calculate除以4，最后给出两个正确数值。

## 我的解释

基线是否完成任务：是。full用4轮、5次工具行动得到正确答案，且每个数字都能追溯到工具结果。

移除信息后出现的具体变化：删除全部历史会造成盲目重复；删除工具定义后模型无法行动；保留调用但清空工具结果后，模型知道自己做过什么，却无法利用观察完成计算。

支持这个判断的轮次、参数或消息：no_history连续5轮都只收到system和user，累计执行15次工具、其中12次重复；no_tool_calls只有1轮且请求中没有tools；no_tool_results共有16条内容为空的tool历史消息，累计7次工具行动、其中4次重复。

与截图不同的现象：本次受系统提示约束，no_tool_calls和no_tool_results没有编造数字，而是明确拒绝回答。这仍然说明任务失败，因为`completed=True`只表示模型停止继续调用，不表示目标已完成。

目前不能从这些运行确定的结论：没有运行DeepSeek的等价no_reasoning组，因此不能用本次结果比较思考过程与工具结果、历史记录之间的相对重要性；单次运行也不能代表所有模型的稳定行为。
