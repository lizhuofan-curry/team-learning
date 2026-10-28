# Codex生成论文PPT验收记录

日期：2026年10月12日。运行目录：`20261012_codex_from_scratch`。

## 产物与范围

从原始15页PDF重新提取文本、裁剪五张原图、规划14页中文大纲和编写HTML。没有读取或复用昨日Kimi的大纲、HTML或裁剪图。实际通过官方`html2pptx.js`生成[presentation.pptx](presentation.pptx)，再用LibreOffice打开并导出[14页PDF](preview/presentation.pdf)。

本次产物生成、LibreOffice兼容渲染和逐页视觉检查完成。没有在Microsoft PowerPoint中实际打开或播放。Skill采用Codex显式分层读取，未独立验证原生启动目录自动发现，详见[渐进式披露过程](渐进式披露过程记录.md)。

## 内容覆盖

| 要求 | 幻灯片 |
| --- | --- |
| 标题与作者 | 1，完整8人名单在演讲备注 |
| 问题背景 | 2 |
| 架构与方法 | 3–8 |
| 训练设置 | 9 |
| 关键实验结果 | 10–13 |
| 结论与适用边界 | 14 |

论文表2与摘要给出Big英法BLEU 41.8，正文6.1写41.0。第10页显示表2数值，同时标注原文不一致。表3的newstest2013开发集与表2的newstest2014测试集分开注明。训练耗时、GPU、BLEU和F1都是论文报告，不是本次训练结果。

## 原图对应

| 原图 | PDF页 | 幻灯片 |
| --- | ---: | ---: |
| Figure 1，架构 | 3 | 3 |
| Figure 2，注意力 | 4 | 4 |
| Table 1，复杂度 | 6 | 8 |
| Table 2，翻译结果 | 8 | 10 |
| Figure 3，远距离依赖 | 13 | 12 |

五张来源裁剪PNG与PPT内媒体均通过字节哈希及指定幻灯片引用关系核对。原图保持比例，无重绘或替换。坐标、200DPI、尺寸与哈希见[manifest.json](source_visuals/manifest.json)。补充中文表格在第6、11、13页为可编辑原生对象。

## 实际执行

1. 共用Python用`pypdf`重新读取原始PDF。
2. Poppler对五个指定原始页执行`pdftoppm -png -r 200 -f N -l N -singlefile`。
3. [extract_visuals.py](extract_visuals.py)裁剪原图并记录来源。
4. Node执行[build.cjs](build.cjs)，逐页真实调用官方`html2pptx()`。
5. 官方缩略图：`python ../../skills/pptx/scripts/thumbnail.py presentation.pptx preview/thumbnails --cols 4`。
6. LibreOffice：`soffice --headless --convert-to pdf --outdir preview presentation.pptx`，实际命令另有独立用户配置目录参数。
7. Poppler：`pdftoppm -png -r 150 preview/presentation.pdf preview/slide`。

以上为便于阅读的短命令，实际完整参数、时间及退出码见[execution_receipts.json](execution_receipts.json)。官方脚本生成[缩略图网格](preview/thumbnails.jpg)，网格编号从0开始，对应PPT页1～14。

## 最终检查

| 项目 | 结果 |
| --- | --- |
| PPT / PDF / 逐页PNG数量 | 14 / 14 / 14 |
| 原图嵌入、对应页关系 | 五张均通过 |
| ZIP包CRC | 通过 |
| 演讲备注与来源 | 14页均有 |
| HTML图像加载失败 / 页面溢出 | 未发现 |
| 形状超出幻灯片边界 | 未发现 |
| 原生表格 | 第6、11、13页各一张 |
| 官方Skill哈希 | 全部56个文件与生成前一致 |
| LibreOffice打开和PDF导出 | 成功，14页 |
| 最终150DPI逐页视觉检查 | 全部14页已检查 |
| Microsoft PowerPoint打开 / 播放 | 未进行 |
| Codex原生Skill目录自动发现 | 未独立验证 |

自动明细：[validation.json](validation.json)。最终PPT SHA256：`b9482a0b6863499816b4f3127f44ced9ccc4869aa10b24b0b1bb273e3f8f0854`。

## 视觉问题及修正

初次第12页文字过近底边，被官方库拒绝。修改后又遇到Windows中文URL图片路径问题，在本次调用入口处理，官方文件保持原样。初版导出并通过包检查后，逐页查看发现第13页`1024`换行与下一段重叠、第10页上沿残留少量标题笔画。改为分段定位及调整裁剪后重新导出并检查。

最终逐页检查：1封面、2背景、3架构原图、4注意力原图与公式、5多头维度、6中文表格、7位置与FFN、8复杂度原表、9训练设置、10结果原表与差异说明、11消融表、12依赖原图、13F1表与设置、14结论。未发现中文缺字、意外裁切、文本重叠或证据图缺失。

检查对象是最终PPT经LibreOffice转PDF后生成的图像，不以HTML截图代替。[过程记录](渐进式披露过程记录.md)和[事件](disclosure.jsonl)保留失败及修正情况，不把它改写为一次成功。
