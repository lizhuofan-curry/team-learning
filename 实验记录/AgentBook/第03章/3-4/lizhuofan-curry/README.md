# 实验3-4：稠密向量检索

日期：2026-10-17。3-3两条合成日志学习范围已收尾。3-4先做向量距离与精确检索基础，再接真实文本嵌入和ANNOY/HNSW对比，不运行3-2剩余190组。

当前进度：二维向量基础与合成向量ANNOY/HNSW对照均已由用户运行并核对。索引召回分别为精确100%、ANNOY 16.9%、HNSW ef=20为55.7%、ef=200为99.2%；高召回HNSW本次耗时与精确排序接近。见[结果总结](03_合成向量索引对照总结.md)。第三步MiniLM真实文本也已实测核对：Recall@5=1、Precision@5=0.32、MRR=1，两索引Top-5与精确一致。[本地CLI学习范围已收尾](04_真实文本结果与实验3-4小结.md)，下一步3-5；未扩展BGE-M3 HTTP服务或大规模压测。

## 第三步已完成：真实文本嵌入与检索

```powershell
& 'E:\AI_Agents_Book\.venv\Scripts\python.exe' 'E:\AI_Agents_Book\第三章\3.4稠密向量检索\我的代码\03_真实文本嵌入与检索.py'
```

使用官方CLI支持的轻量替代路线sentence-transformers/all-MiniLM-L6-v2，版本固定为1110a243fdf4706b3f48f1d95db1a4f5529b4d41。所需10份文件共91,578,299字节，已下载到E:\AI_Agents_Book\.uv-cache\huggingface\local_models\all-MiniLM-L6-v2_1110a243fdf4，并按公开Git blob/LFS SHA256逐项校验，见[模型清单](官方资料/MiniLM模型清单.json)。权重缓存已被既有.gitignore排除，不提交模型文件；没有新增Python依赖。

原样使用官方12篇英文文档与5条查询/标注，分别编码文档和查询，共17段文本、预计2批本机嵌入前向。复用官方DenseEncoder的掩码平均池化和L2归一化，CPU float32、384维、batch_size=16、CPU线程4。按[模型说明](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2)设置最大长度256；官方CLI默认512，本组文本实际最长25 token，均不会截断。正式脚本已强制离线，只读已验证文件，不调用Ollama、云端或自动下载。

终端会分别显示：

1. 精确向量检索与官方人工标注比较的Recall@5、Precision@5及MRR。召回分母是该查询的相关文档数量；MRR沿用官方完整12文档排名，不写成MRR@5。标注每题仅1或2篇，固定Top-5时Precision宏平均上限为0.32，不能将这个上限误解为模型运行失败。
2. 同一批真实嵌入上的ANNOY和HNSW Top-5结果，以及它们相对精确Top-5的索引召回，分母固定为5。这个指标只检查近似索引是否漏掉近邻，不替代人工标注相关性。

保存完整排名、分数、向量数组、模型和官方材料哈希、标注与指标、前向批次和失败状态，供后续逐项复核。沿用官方主题级标注，不把某些猫科相关文本自动改判成“正在玩耍”，也不擅自修订参考答案。仅12篇的小语料不用于性能排名；MiniLM替代路线不写成BGE-M3复现结果。

[13项离线检查](文本嵌入离线检查_20261017.json)与实际--preview已通过，包括模型文件、Tokenizer、BERT框架导入、权重头形状、指标定义及非法向量拒绝。没有构造模型执行前向，也没有语义成绩。用户已完成text_embedding_20261017_213507_432933，2批前向、17段文本，完整排名和指标已按保存数组复算；独立核对记录保留，不用原作者README分数代替本人结果。上述命令保留为入口，无需为核对重跑。

## 第一步要看懂什么

稠密检索包含两件事：嵌入模型将文本变成向量；搜索算法从已有向量中找近邻。第一步只解释后半部分的距离和精确排序，使用6个手工指定的二维坐标，让你能直接看图。

查询q=(1,0)，向右。A与q同方向，B略偏，C呈45度，D垂直，F反向。将向量长度归一化后计算点积，就是余弦相似度；相似度越大，方向越近。这里的“余弦距离”定义为1−相似度。

这是人工坐标练习，不给向量贴上猫、法律等文本标签，也不声称证明模型懂语义。精确检索会遍历所有6个向量；后续近似索引才需要检查是否漏掉精确近邻。

## 第一步已完成：二维向量精确检索

```powershell
& 'E:\AI_Agents_Book\.venv\Scripts\python.exe' 'E:\AI_Agents_Book\第三章\3.4稠密向量检索\我的代码\01_向量距离与精确检索.py'
```

模型请求0、网络请求0，不需要下载新模型或安装依赖；使用共用环境已有numpy。运行会打印六个候选的相似度、距离及Top-3，并保存record.json和可打开的向量方向.svg。输出发来后核对，再讲解每一行如何计算。

用户已运行并核对[正式记录](运行结果/exact_vectors_20261017_194826_596079/record.json)与独立[核对记录](运行结果/exact_vectors_20261017_194826_596079/核对记录.json)。顺序为A、B、C、D、E、F，Top-3为A、B、C。A同向，余弦1、距离0；D垂直，余弦0、距离1；F反向，余弦−1、距离2。B相似度0.993884、C为0.707107。公式重算、源文件及SVG哈希均通过。原脚本与原始结果保持不变。

加--preview仅核验材料、不创建运行目录。之前[10项离线检查](离线检查_20261017.json)属于准备验证，与上述用户实测分开。

## 已完成第二步：合成向量ANNOY/HNSW对照

准备了[02入口](我的代码/02_合成向量ANNOY与HNSW对照.py)。沿用官方CLI的3000条底库、128维、100次查询、数据种子42及Top-10设定，归一化float32后，用官方dense_rank建立精确基准，调用官方索引类检索。比较ANNOY的10棵树、HNSW的M=16和ef_construction=100；同一张HNSW图依次使用ef_search=20、200，观察扩大搜索范围能否减少遗漏。

Recall@10表示每次找回的精确Top-10中有几条命中。例如命中8条就是80%；这是索引召回，不是文本相关性。保留逐查询ID、距离、耗时、精确答案、数组及SHA256，可逐项复算。ANNOY angular距离为sqrt(2−2cos)，HNSW cosine距离为1−cos，两种距离数值不能直接混比。

这是教学适配：HNSW容量设为实际底库大小，原生查询线程设1；ANNOY沿用官方重建方法，使用库默认建树线程；原生索引随机种子未覆盖。数据种子固定不意味着所有库构建过程位级可复现。精确查询时间包含逐条点积和全排序，ANN时间包含官方Python封装。只测一次本机耗时，不据此声称通用速度排名。

### 本机环境已补齐

2026-10-17晚，按用户要求完成已有D盘Build Tools实例的安装，MSVC与Windows SDK均确认完整、可用，不需要重启；安装缓存沿用D盘。annoy==1.17.3、hnswlib==0.8.0、colorlog==6.8.0已通过uv安装到项目共用.venv，编译缓存放在E盘。原有54个Python包版本、uv.lock及两份实验脚本哈希保持不变。见[C++安装记录](安装记录/build_tools_install_20261017.json)、[uv同步记录](安装记录/uv_sync_index_20261017.json)及[原生健康检查](安装记录/native_index_health_20261017_204929_172551.json)。

实际--check-only通过；随后用6条二维向量、1次查询，验证官方ANNOY/HNSW类真实建索引、查询和自身向量检查，均返回正确Top-3。这份记录只验证环境可用；随后用户已另行运行3000条底库、100次查询的正式对照，见上方结果小结。当时未下载嵌入模型；当前MiniLM真实文本阶段也已另行完成并核对，见上方收尾小结。

之前缺少编译工具的失败快照[原环境检查](索引环境检查_20261017.json)保留。以下是新机器复现安装的步骤，本机无需重复执行安装：

1. 从[Microsoft C++ Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/)安装编译工具。按微软[安装说明](https://learn.microsoft.com/en-us/cpp/build/vscpp-step-0-installation?view=msvc-170)，选择“使用C++的桌面开发”，包含MSVC x64/x86工具和Windows SDK。这里只需要Build Tools，无需完整Visual Studio编辑器。安装结束后重新打开PowerShell。
2. 在项目目录同步可选依赖：

```powershell
& 'E:\Hermes\bin\uv.exe' sync --project 'E:\AI_Agents_Book' --locked --inexact --group chapter3-index --cache-dir 'E:\AI_Agents_Book\.uv-cache'
```

3. 检查实际原生库导入：

```powershell
& 'E:\AI_Agents_Book\.venv\Scripts\python.exe' 'E:\AI_Agents_Book\第三章\3.4稠密向量检索\我的代码\02_合成向量ANNOY与HNSW对照.py' --check-only
```

本机已通过ANN_IMPORT_CHECK_ONLY。正式合成向量对照入口如下（本次已完成运行）：

```powershell
& 'E:\AI_Agents_Book\.venv\Scripts\python.exe' 'E:\AI_Agents_Book\第三章\3.4稠密向量检索\我的代码\02_合成向量ANNOY与HNSW对照.py'
```

脚本无网络、无自动安装或模型请求。依赖没准备好时退出，不创建正式运行目录。用户已完成本次运行，原始结果与独立核对保存在synthetic_ann_20261017_205150_250997；上面的命令保留为入口说明，无需为核对而重跑。

[8项离线检查](索引对照离线检查_20261017.json)与6条向量原生健康检查属于环境准备证据；正式规模的ANNOY/HNSW对照已另行运行和核对，不混用两个阶段的成绩。

## 固定材料与边界

官方资料固定到dbc046eb896ac4e39aa19c7774c8bf49583b89a6，共27份公开文件，逐文件Git blob和SHA256核验，见[清单](官方资料/manifest.json)。原作者validation记录不是本人结果。

入口只从已校验的官方cli.py抽取dense_rank纯函数，用于归一化后精确排序；不导入该模块顶层的索引依赖或启动模型下载。人工二维坐标属于本地教学材料，不替代官方合成向量ANN对比或真实嵌入评测。

共用环境原有numpy、torch、transformers；索引阶段已补齐annoy、hnswlib、colorlog三个依赖。文本阶段已准备MiniLM固定版本文件，继续使用现有torch/transformers，不安装整个HTTP服务或下载BGE-M3。

## 后续顺序

1. 给定向量的精确近邻：用户实测和核对已完成。
2. 固定合成向量比较ANNOY/HNSW与精确基准：3000向量、100查询已由用户实测核对并总结。
3. 用同一嵌入模型将文本变成向量，再检验文本相关性：MiniLM真实文本已完成2批前向和检索，12文档5查询结果已独立核对；模型效果与索引近似误差分开。

三步均已由用户实测并独立核对，本地MiniLM CLI学习范围完成，见[收尾核对](3-4学习范围完成核对_20261017.json)与[实验记录](3-4_lizhuofan-curry_实验记录.md)。内存占用、增量更新和大规模服务压测未开展，不将它们写成已验证。
