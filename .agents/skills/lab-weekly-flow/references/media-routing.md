# 多平台链接：选型与接入

用于收到视频分享链接、排查“网页能打开但Hermes读不到内容”或选择媒体组件时。沿用[对话与多媒体](conversations-and-media.md)的来源规则，验收按[媒体验收](media-acceptance.md)。以下选型经过代码检查，不表示已经安装或通过每个平台的真实链接测试。

## 处理顺序

1. 保留原消息；从分享文字提取URL，解析实际作品与分P。清理跟踪参数时保留影响内容的作品编号、分P及播放区间。短链尚未解出来源时不猜作品编号。
2. 先辨别文章、图文作品与视频。文章取正文；图文作品取作者文案和画廊图片，逐张读图并登记实际页数，不走字幕或音轨转写；视频先取实际人工字幕或平台AI字幕。标题、简介、图文文案、评论、弹幕与口播分开。
3. 字幕不可得时区分登录/网络受阻、接口返回空列表与已确认无字幕。仅在取得音轨且范围明确时转写；沿用成员选定的STT。未选择长视频政策的成员不默认处理完整长视频；本人已选择full_when_no_subtitles时按持续授权处理整段，分段适配服务限制，不重复索要同意、不切提供商。完整覆盖与分段识别均须核对，见[媒体队列](media-queue.md)。
4. 记录实际取得的内容与时间戳。整条字幕轨道成功不表示覆盖全片；没有字幕的尾段、静音、图表与操作演示仍可能未读。需分析画面时另核对指定帧或片段。

## 组件选择

| 组件 | 适合借鉴的部分 | 本次代码检查发现的边界 |
|---|---|---|
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | 多站元数据、字幕和按需音轨提取 | 有提取器不等于当前链接可用；抖音仍可能报fresh cookies。当前源码依赖Python3.11+，与学习脚本的3.9+分别配置；Windows可使用官方独立程序 |
| [bili-subtitle](https://github.com/ymt200120/bili-subtitle/tree/b3f43e4a08bb2cc3580fa19c1fe94d298ca23a30) | 当前播放器字幕资源发现、作品/分P绑定和导出 | 浏览器侧工具，不能直接装到无浏览器的云Hermes；AI字幕通常涉及登录，旧匿名接口空列表不能判定无字幕 |
| [video-subtitle-parser](https://github.com/threerocks/video-subtitle-parser/tree/777ff78ff81f4294160ae5c2f44cff81dfeb00cb) | 抖音公开移动分享页解析 | 当前抖音路径下载视频后ASR，没有字幕优先；短链解析不完整，ASR仅mlx-whisper，不能直接承诺Windows/Linux支持 |
| [douyin-mcp-server](https://github.com/juziguai/douyin-mcp-server/tree/bc3ae50e83eabd0edea25230c0ed719d0f782e59) | 抖音字幕字段选择、faster-whisper按需准备 | 详情依赖签名接口及配置；包含额外账号功能。不能整套默认授权，字幕秒/毫秒及Cookie随下载Session发送的处理需要独立复核 |
| [DouK-Downloader](https://github.com/JoeanAmier/TikTokDownloader/tree/473c90ff70c663cfb69310fff2b8d5192f200661) | 抖音/TikTok媒体取得备用组件 | 下载成功仍需字幕或转写，不等于视频正文已读 |

不选择[transcriptor](https://github.com/crunchtools/transcriptor/tree/a27afe7e6f24eaca76e8ca6b8db87f96ab1a1ce6)直接覆盖抖音：本次核对时已归档，URL校验也没有douyin.com/v.douyin.com；TikTok支持不能替代抖音支持。项目状态与平台接口会变化，实际接入时重新核对固定版本。

## 本地与云端分别执行

本地Hermes：在同机使用已配置的平台工具与STT；缺依赖先说明具体组件和安装范围。macOS的MLX、Windows的可执行文件、Linux的CPU/CUDA运行时分别验证，不由核心脚本跨平台推断媒体组件也可用。

云端Hermes：先尝试本机现有工具。受阻时保留原链接为待处理资源。用户已授权的Mac/Windows端可取得字幕或限定音轨，再把文本结果传回自己的云端；默认不搬浏览器Cookie、不把账号或签名媒体URL交给第三方解析站。若必须让新工具使用账号，由本人完成具体登录授权，凭据留在选定机器。

已授权的浏览器能播放字幕时，可用浏览器工具列出的当前页面资源定位官方字幕；使用当前作品/分P、页面会话和一处可见字幕核对归属，再用不带账号Cookie的独立请求读取可访问资源。工具不能导出某类资源时，不改为读取隐藏应用状态或凭据。不可见资源不凭路径猜测。

匿名HTTP请求返回外壳、空响应或风控错误，只能证明该请求路径受阻，不能据此断言必须登录。本人授权的普通浏览器可能在未登录时已能显示正文；优先核对一次实际渲染页面。图文可通过浏览器工具导出当前页面已观察到的画廊资源，按页码读图并核对总张数。仅导出图片不算读图；作者实验数据按作者陈述记录，不升级为本人复现。回传可读包后先复用该包，不再对同一链接重复尝试相同失败接口。浏览器也不可读时保留待处理，不绕过访问控制。

旧标签控制失效时先按[队列的浏览器恢复步骤](media-queue.md)尝试一次独立新页，区分旧句柄失败与实际连接中断；新页仍失败才延后。下载操作按工具要求串行，公开资源的独立请求仅限页面已经显示的确切URL。

Mac在线时，Codex可在学习汇总中处理链接；需要自动补读时按[媒体队列](media-queue.md)另外启用。`learning_flow.py sync`本身仍只传学习收件和批准记录；启用后的协作tick只发现资源并排队，浏览器由本人授权的Codex定时任务调用。分别核对队列、调度、浏览器读取与回传，不为媒体任务改动每日汇总时刻或承诺离线处理。

## 文本结果交接

需要Hermes读取Mac处理结果时，可放在成员自己的`workflow_root/媒体结果/平台/作品编号/`。目录名只使用核对过的字母、数字、短横线与下划线；分P单独登记。普通网页或无稳定作品ID的资源可使用规范URL的SHA256，不能把整条URL直接当路径。

`result.json`至少含：`schema_version`、`canonical_url`、`platform`、`resource_id`、分P、`status`、`content_source`、取得时间、内容文件相对路径及SHA256、实际覆盖区间、`visual_verified`和`test_only`。状态使用`subtitle_ready / transcript_ready / article_ready / partial_ready / blocked / failed`；`partial_ready`只用于已取得的作者文案、平台AI要点或有限片段，另记未取得的部分。网络受阻时另记错误阶段，不伪造字幕/转写ready。平台AI字幕、平台AI章节摘要与本地ASR分别标注。

读取前核对URL/编号/分P、文件路径在该结果目录内、SHA256与覆盖范围。文件存在只证明可读取，模型需实际分段读取请求范围后才能总结。测试包不进入学习日记或周报；真实学习效果仍由本人反馈确认。保持原平台内容与AI辅助摘要分开。

图文包补充`resource_kind: note_image_post`、`images_expected_from_page`、`images_obtained`、`images_visually_read`及每张图片的相对路径、SHA256、页码与实际读图标记。只有正文及声明范围内的图片均已读取时用`article_ready`；缺页、未读图片或只取得文案时用`partial_ready`并列明缺项。更新失败包时保留旧失败记录和原始链接消息。

交付时分别报告“源码已查、组件已安装、取得内容、本地→云传输、Hermes实际读取、微信端到端”。缺哪层就写哪层；一次浏览器辅助提取不称全平台自动读取已实现。
