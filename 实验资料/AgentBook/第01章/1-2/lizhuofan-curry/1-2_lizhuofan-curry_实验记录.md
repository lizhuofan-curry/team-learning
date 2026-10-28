> 记录归属：李卓凡 / `lizhuofan-curry`。原文件：`第一章/1.2网络搜索Agent/实验记录.md`。
> 来源项目提交：`162191203b31ee701f66a1b55b334915f31626e0`；原文SHA-256：`1eb99b4bf34dd1075203a2f0a8e837e33250550b62c3e97ebf64e922628ae42c`。
> 2026-10-28导入已有记录，保留正文、真实运行/离线/参考/计划的原有区分；仅增加归档说明并调整必要相对链接，不代表本次重新运行。附件按本人目录隔离。

# 实验1.2：真实网络搜索Agent记录

问题：请搜索Moonshot AI的Context Caching官方说明，解释这是什么技术，并提供来源链接。

模型：kimi-k3。记录核对日期：2026-10-05。

## 本次执行

| 模型轮次 | 请求入口 | 发送消息数 | 本轮回复 | 随后执行的搜索数 |
|---|---|---|---|---|
| 1 | 03 | 2 | tool_calls | 3，由04执行 |
| 2 | 05 | 6 | tool_calls | 3，由06执行 |
| 3 | 06 | 10 | tool_calls | 3，由06执行 |
| 4 | 06 | 14 | stop，回答非空 | 0 |

同一问题共4轮模型请求、3轮工具执行、9次搜索。02的普通对话是独立连通检查，不计入本问题。9次搜索均返回HTTP200、status=succeeded，输出字段均为encrypted_output。

最终记录为status=answered、finish_reason=stop、answer_complete=True、model_turns=4、pending_calls=[]。完整历史共15条消息，最后一条是最终回答。

本地逐条核对了：03与05的历史能够接续；每个工具调用都有且只有一条匹配ID的tool消息；执行参数保留模型原始字符串；回传内容与实际保存的工具输出相同；每轮模型请求前，上一轮的全部工具结果均已加入历史。

## 消息数如何增加

初始system与user共2条。前三轮模型各增加1条assistant消息，并分别提出3个调用；每轮执行后再增加3条tool消息，因此请求消息数为2→6→10→14。第4轮只增加最终assistant回答，最终历史长度为15。

一条assistant消息可以包含多个tool_calls，所以模型轮数不等于搜索次数。循环上限5是最多允许的轮数；收到stop且回答非空时，break可以提前退出。本次在第4轮退出。

## 回答来源核对

| 回答内容 | 核对结果 | 来源 |
|---|---|---|
| 重复请求前缀可缓存复用，适合固定文档、系统提示和工具定义 | 当前官方文档支持 | [上下文缓存最佳实践](https://platform.kimi.com/docs/guide/context-caching) |
| 默认5m，可选1h；mode为implicit；命中后按原TTL续期 | 当前官方文档支持 | [上下文缓存最佳实践](https://platform.kimi.com/docs/guide/context-caching) |
| kimi-k3示例价格：未命中20、5m写入20、1h写入40、命中2元/1M tokens | 与核对时官方文档表格一致 | [上下文缓存最佳实践](https://platform.kimi.com/docs/guide/context-caching) |
| 首Token延迟下降约83%、费用最高下降90% | 属于2024年公测博客的示例与测试场景，不能作为本次实测结果或普遍保证 | [2024年公测说明](https://platform.kimi.com/blog/posts/context-caching) |
| 早期显式缓存的创建、存储、调用三项费用 | 与2024年博客一致，需要保留历史版本限定 | [2024年成本案例](https://platform.kimi.com/blog/posts/how-to-save-90-percent-with-context-caching) |
| 回答第5条FAQ链接被列为缓存依据 | 旧地址可访问，但重定向后的当前页面没有缓存说明，不能支撑该主题 | [当前问题排查页](https://platform.kimi.com/docs/guide/troubleshooting) |

保留模型原始回答，不直接覆盖运行JSON。引用缓存定义与现行参数时，应优先使用当前缓存文档；引用旧博客数据时说明年份和场景。

## 本次证据的范围

本次真实运行证明：工具定义获取、模型提出调用、Formula执行、匹配ID回传、多轮搜索、最终回答与保存均已完成。答案中的主要技术说法已经对照公开官方页面核查。

工具输出加密，因此本地无法逐段阅读其检索内容，不能确定某个具体段落来自哪一次搜索。记录没有缓存usage和响应计时，无法据此测量本次缓存命中率、费用降幅或首Token延迟；这些需要额外的用量记录或对照实验。

## 07：统一入口的独立问题

问题：Python3.12有哪些新特性？请搜索Python官方文档，概括3个变化并提供来源链接。

用户已真实运行07，从统一入口完成新问题。第1轮发送2条消息，返回1个调用，ID为web_search_0_cd091315；搜索HTTP200、status=succeeded，encrypted_output长度7074字符。第2轮发送4条消息，返回stop。最终status=answered、answer_complete=True、model_turns=2。

conversation_history共有5条：system、user、assistant调用消息、tool结果、assistant最终回答。api_turns共有4条：formula_tools、chat_completion、formula_fiber、chat_completion。trace共有行动、观察、回答3条。两次模型请求都保存了服务返回的usage，本次不据此推算费用。

回答中的f-string语法放宽、类型参数与type语句、子解释器独立GIL均有[Python3.12官方说明](https://docs.python.org/3/whatsnew/3.12.html)支持；设计细节分别见[PEP701](https://peps.python.org/pep-0701/)、[PEP695](https://peps.python.org/pep-0695/)、[PEP684](https://peps.python.org/pep-0684/)。3.12的独立子解释器GIL主要通过C API提供。

该问题的记录位于运行结果/kimi_agent_python312.json，与前一个Context Caching问题分别保存。Agent仍在项目Python3.11环境中运行；查询3.12特性无需调整当前环境。

## 08：连续处理两个独立问题

用户于2026-10-05真实运行08交互入口，连续提问Python3.11特性与开封天气，最后输入exit正常退出。两题均完成真实搜索与结果回传。

| 问题 | 模型请求轮数 | 成功搜索次数 | 每轮发送消息数 | 最终历史数 | 接口记录数 |
|---|---|---|---|---|---|
| Python3.11新特性 | 5 | 6 | 2→4→6→10→12 | 13 | 12 |
| 今天开封天气怎么样 | 2 | 1 | 2→4 | 5 | 4 |

两题均为status=answered、finish_reason=stop、answer_complete=True。Python题的12条api_turns为1次定义GET、5次模型请求、6次搜索POST；天气题的4条为1次GET、2次模型请求、1次POST。搜索记录均为status=succeeded，输出字段为encrypted_output；调用ID与tool消息数量一致。

Python题前三次工具执行分别为1、1、3次，第四次为1次。第3轮的3个调用使消息数从6增加到10；第4轮的1个调用使消息数从10增加到12。第5轮回答被加入历史，最终为13条。5是最多允许的模型轮数，第5轮获得有效stop仍为正常完成。

第二题初始历史仍为system和user两条，没有继承上一题内容。第一题输入前缀包含“输入”与左引号，原始问题在JSON中保留；后续输入只需填写问题本身。

原始记录分别位于：

- [Python3.11问答](运行结果/交互问答/20261005_154724_750813.json)
- [开封天气问答](运行结果/交互问答/20261005_154931_900353.json)

### 来源核对

Python回答中的CPython3.11性能提升、ExceptionGroup与except*、新增只读TOML解析模块tomllib，以及补充的细粒度错误定位，均有[Python3.11官方说明](https://docs.python.org/3.11/whatsnew/3.11.html)支持。性能数据是官方相对3.10的基准结果，不是本次运行的实测加速。

天气答案引用的[中国天气网开封页面](https://www.weather.com.cn/weather/101180801.shtml)在本次读取时仍显示4日为“今天”、5日为“明天”；5日条目为多云、23℃/13℃、小于3级，6日为晴、26℃/12℃。这些温度与风力支持模型给出的数值，但当前读到的版本无法确认模型所说的“07:30更新”和“晴转多云”。保留模型原文，不将搜索接口成功视为答案逐项正确。查询天气等实时信息时，应同时检查日期、发布时间与来源版本。

## 09：命令行参数与达到轮数上限

问题：请搜索Python官方文档，解释Python3.11的ExceptionGroup，并提供来源链接。

PyCharm运行配置的参数正确传入：max_steps=5、quiet=False，output=None。未指定输出文件，使用默认的时间文件名。

| 模型请求轮次 | 发送消息数 | 回复结束原因 | 新调用数 | 实际执行搜索数 |
|---|---|---|---|---|
| 1 | 2 | tool_calls | 3 | 3 |
| 2 | 6 | tool_calls | 4 | 4 |
| 3 | 11 | tool_calls | 3 | 3 |
| 4 | 15 | tool_calls | 3 | 3 |
| 5 | 19 | tool_calls | 3 | 0，达到上限 |

共5轮模型请求、13次成功搜索，均为HTTP200、status=succeeded。最终api_turns共19条：定义GET1次、模型请求5次、搜索POST13次；conversation_history共20条，tool消息13条。第5轮提出的3个调用被保存到最后的assistant消息中，但未执行。

最终状态为status=max_turns_reached、finish_reason=tool_calls、answer_complete=False、answer为空。09捕获RuntimeError后继续抛出，finally先保存已有记录，随后显示Traceback。该输出证明轮数控制已生效，不能视为问答完成。

原始记录：[20261005_164034_952797.json](运行结果/命令行问答/20261005_164034_952797.json)。已逐项核对前4轮的调用ID、原始参数、tool内容长度与观察记录，最后3个调用仍待执行。

有4次加密输出长度为158字符；由于记录没有可读检索结果与模型推理字段，不能仅据此判定无结果，反复检索的具体原因尚不确定。回传加密输出的做法符合[Moonshot官方工具说明](https://platform.kimi.com/docs/guide/use-official-tools)。

### 09再次运行：缩小范围后完成问答

新问题：请搜索Python3.11官方文档，用100字以内解释ExceptionGroup，给出1个官方链接。完成一次搜索后，根据已有结果回答；如果证据不足，请明确说明。

参数仍为max_steps=5、quiet=False、output=None。第1轮发送2条消息，提出1次web_search调用，ID为web_search_0_cc5d9996；工具HTTP200、succeeded，加密输出6366字符。第2轮发送4条消息，返回stop与非空回答。

最终status=answered、answer_complete=True、model_turns=2、conversation_history长度5、api_turns长度4、trace长度3。已核对调用ID、原始参数、tool内容长度、观察记录和最终回答。

原始记录：[20261005_164921_331811.json](运行结果/命令行问答/20261005_164921_331811.json)。它与首次未完成的记录分别保存。

回答关于ExceptionGroup与except*的定义及并发场景有[Python3.11官方教程](https://docs.python.org/3.11/tutorial/errors.html#raising-and-handling-multiple-unrelated-exceptions)支持。两次都使用相同5轮上限，本次较具体的问题在2轮内完成；这是两次运行的观察，不能保证同一提示以后每次都只搜索一次。

### 09第三次运行：quiet隐藏打印，搜索仍执行

用户在相同提问与--max-steps 5后添加--quiet，解析结果为quiet=True、output=None。终端未打印搜索过程，仍打印最终回答与保存路径。

JSON确认此次实际执行2轮模型请求、1次搜索：第1轮发送2条消息，调用ID为web_search_0_14187401_532ae46e；工具HTTP200、succeeded，加密输出8366字符。第2轮发送4条消息，返回stop。

最终status=answered、answer_complete=True、model_turns=2，历史消息5条、接口记录4条、trace3条（行动、观察、回答）。run_options.quiet=True。已核对调用ID、原始参数、tool内容、观察记录和最终回答。

原始记录：[20261005_165645_741223.json](运行结果/命令行问答/20261005_165645_741223.json)。这次真实运行证明quiet仅控制打印，实际搜索与JSON记录仍执行。

回答中的ExceptionGroup容器、嵌套结构及except*类型匹配有[Python官方文档](https://docs.python.org/3.11/library/exceptions.html#ExceptionGroup)支持。“多个相关异常”不应理解为只能包含相关异常；更准确的说明是可将多个异常一起抛出，也可以互不相关。原始模型回答继续保留。

### 09第四次运行：指定输出文件

用户添加--output "命令行问答/ExceptionGroup_指定输出.json"，Namespace的output解析为该路径字符串；文件已实际保存到本实验运行结果目录下的命令行问答文件夹。

JSON确认2轮模型请求、1次成功搜索。调用ID为web_search_0_b10a7ed2；工具HTTP200、succeeded，加密输出6034字符。两轮请求发送2条与4条消息，第2轮stop；最终status=answered、answer_complete=True，历史5条、接口记录4条、trace3条，quiet=True、max_steps=5。已核对调用ID、原始参数、tool内容与最终回答。

原始记录：[ExceptionGroup_指定输出.json](运行结果/命令行问答/ExceptionGroup_指定输出.json)。这次实际验证了相对输出路径从本实验运行结果目录拼接，而不是自动生成时间文件名。

模型回答开头为“现有搜索结果未直接定义”，说明其对当前检索证据有所保留。输出加密，无法从本地逐段核查定义究竟来自哪条检索内容；参数功能与循环完成已验证，回答的来源支撑仍需独立检查。

## 10第一次真实搜索：选择现成问题

用户先输入3验证正常退出，随后重新运行，选择模式1、问题1，搜索“OpenAI最新发布了什么产品？”，问答后输入n退出。

JSON确认2轮模型请求、2次搜索，两次工具均HTTP200、succeeded，加密输出分别为6290与6726字符。请求消息数2→5，最终历史6条，接口记录5条；最终status=answered、answer_complete=True、finish_reason=stop。

原始记录：[20261005_172519_494970.json](运行结果/引导式体验/20261005_172519_494970.json)。模式菜单、现成问题选择、真实搜索、保存与退出均已运行。

回答将当前日期说成2026-09-24，实际运行日期为2026-10-05；首个搜索词还加入了May 2026。当前system消息没有提供日期，因此该结果暴露出时间信息缺失的问题，不能将模型声称的日期视为程序实际配置。产品名称、发布日期与价格未在本次核对中独立验证。程序循环完成不等于回答事实全部正确。

## 完成状态

实验1.2已完成（2026-10-05），由本人确认结束本阶段学习。07与08均已真实运行；09已实际观察提问参数、轮数上限、失败记录保存、正常回答、quiet与指定文件路径；10已实际验证退出分支及模式1的现成问题搜索。高级示例暂缓，不新增相关代码；10的自定义问题与演示后继续交互分支不再追加真实练习。原始记录、未完成的调用记录及答案准确性分析均保留。

## 2026-10-14：09重新运行时遇到429

用户使用原ExceptionGroup问题、max_steps=5、quiet=True及指定输出路径重新运行。获取Moonshot搜索工具定义的GET接口返回429，当前失败记录中model_turns=0、tools=null、trace和api_turns均为空，answer_complete=False。没有实际搜索，也没有模型回答。

指定输出路径覆盖了之前同名记录。本次失败已按原始字节另存[20261014_工具定义429_原始记录.json](运行结果/命令行问答/20261014_工具定义429_原始记录.json)。此前带时间戳的成功记录继续保留；不能将当前同名失败文件描述为成功。

代码改动：仅为工具定义GET增加有上限的429重试、Retry-After解析和错误诊断留档。最多3次尝试、累计等待不超过60秒；长时间等待、余额/配额和日额度提示停止重试。模型仍为kimi-k3，未切换DeepSeek。

离线核对通过：429后恢复并复用定义、连续429的次数与等待上限、2220秒长等待立即停止、配额/日额度不重试、401不重试、HTTP日期解析、无效头回退及测试密钥遮蔽。首次测试因测试环境代理配置影响SDK初始化而失败；改用模拟SDK客户端后上述检查通过，没有读取真实密钥或调用API。

状态：限流处理代码已修正，真实接口恢复情况未验证。此次失败不改写10月5日已完成学习阶段的历史结论。
