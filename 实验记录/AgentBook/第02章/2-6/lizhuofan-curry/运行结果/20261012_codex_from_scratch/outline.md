# Codex重新生成的论文PPT大纲

来源：本次重新提取的原始PDF；不读取昨日HTML或大纲。
设计：白底、深蓝文字、青色强调，16:9，论文原图保持比例。

## 1. Attention Is All You Need
来源：PDF第1页。
原论文8位作者：Ashish Vaswani、Noam Shazeer、Niki Parmar、Jakob Uszkoreit、Llion Jones、Aidan N. Gomez、Łukasz Kaiser、Illia Polosukhin。论文发表于NIPS 2017，本次文件为arXiv v7，2023年更新。标题和作者见PDF第1页。

## 2. 序列建模中的顺序计算
来源：PDF第2页。
PDF第2页Introduction、Background和Model Architecture。最后一点依据原论文自回归解码描述，不把训练并行误写为一次生成全部输出。

## 3. 编码器与解码器架构
来源：PDF第3 · Figure 1页。
PDF第3页Figure 1与3.1节。图为原始PDF重新渲染裁剪。注意这是2017年模型的Post-LN结构。

## 4. 缩放点积注意力
来源：PDF第4 · Figure 2页。
PDF第4页式1和Figure 2。维度较大时点积幅度增大，缩放用于避免softmax进入梯度很小的区域。图保持原文件比例。

## 5. 多头注意力的维度
来源：PDF第4–5 · §3.2.2页。
PDF第4–5页3.2.2节，最后一句是为本章学习者区分模型配置的解释，不是原论文对Qwen的评价。

## 6. 三种注意力的输入与可见范围
来源：PDF第5 · §3.2.3页。
PDF第5页3.2.3节。这里是中文整理表，表格为可编辑原生对象。掩码与输出右移共同保证预测不读取未知未来输出。

## 7. 位置信息与前馈网络
来源：PDF第5–6 · §3.3、§3.5页。
PDF第5页3.3节与第6页3.5节。位置编码帮助模型利用位置顺序，不是语言语义的替代。前馈网络在各位置共享同层参数，各层参数不同。

## 8. 自注意力的计算代价
来源：PDF第6–7 · Table 1页。
PDF第6页Table 1和第6–7页Why Self-Attention。表是论文原图。O(1)路径与O(n²d)复杂度描述不同指标，不能混用为恒定计算开销。

## 9. 数据与训练设置
来源：PDF第7–8 · §5页。
PDF第7页5.1–5.3节、第8页5.4节。Base 100000步，Big 300000步。英法Big dropout 0.1，原文另有说明。这里的warmup是训练学习率预热，不是本章服务请求预热。

## 10. 机器翻译结果
来源：PDF第8 · Table 2、§6.1页。
PDF第8页Table 2的newstest2014测试结果。Base英德27.3、英法38.1；Big英德28.4、英法41.8。PDF第1页摘要与Table 2一致，但第8页正文6.1写41.0。未自行断定哪个是笔误。FLOPs由论文根据时间、GPU数和估计性能计算，并非本次测量。

## 11. 组件变化与开发集表现
来源：PDF第9 · Table 3页。
PDF第9页Table 3，选取(A)头数与(E)位置嵌入行制作可编辑摘要表。各头的dk、dv随头数调整以维持计算规模。开发集为newstest2013，不是Table 2的newstest2014。

## 12. 注意力中的远距离依赖
来源：PDF第13 · Figure 3页。
PDF第13页附录Figure 3。作者描述对making…more difficult的远距离依赖。最后一句为解释边界，不把注意力权重等同于答案因果贡献。图为原始论文裁剪。

## 13. 英语成分句法分析
来源：PDF第9–10 · Table 4页。
PDF第9页6.3节、第10页Table 4。这里仅整理Transformer两行，不声称超过表中全部模型：Dyer generative为93.3，Luong multi-task为93.0，条件不同。

## 14. 贡献与适用边界
来源：PDF第2、6–10 · §7页。
PDF第10页Conclusion，第2页自回归描述和第6页复杂度。论文原图归原作者，本汇报仅用于学习。主要来源：https://arxiv.org/abs/1706.03762。
