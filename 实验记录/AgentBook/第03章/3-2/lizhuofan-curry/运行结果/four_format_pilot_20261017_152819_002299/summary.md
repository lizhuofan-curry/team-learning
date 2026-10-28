# 实验3-2：银行单题四格式预实验

银行单题四格式预实验；不是60题×四格式完整评估，不与3-1的schema成绩合并

固定qwen3:4b、原JSON输出、推荐采样、seed=37、窗口32768、记忆/答题上限6000/1200。
生成或评分失败无reward，不填0；本表不能确定四种格式的总体优劣。

| 模式 | 生成状态 | 评分状态 | 输入token | 输出token | 请求耗时/秒 | passed | reward |
| --- | --- | --- | ---: | ---: | ---: | --- | --- |
| notes | incomplete | pending | 2217 | 681 | 32.62 | — | — |
| enhanced_notes | incomplete | pending | 2220 | 1084 | 38.47 | — | — |
| json_cards | incomplete | pending | 3022 | 2040 | 68.08 | — | — |
| advanced_json_cards | saved | scored | 4344 | 2840 | 103.98 | False | 0.0 |

token与耗时包含失败请求，来自实际记录；耗时含请求开销，不是纯推理时间。
生成与评分各自单独留存；未评分的完整回答需后续运行judge。

## 原始记录

- notes
  - [writer原始记录](../../../../3-1/lizhuofan-curry/运行结果/official_writer_20261017_152825_771379/record.json)
- enhanced_notes
  - [writer原始记录](../../../../3-1/lizhuofan-curry/运行结果/official_writer_20261017_152904_922252/record.json)
- json_cards
  - [writer原始记录](../../../../3-1/lizhuofan-curry/运行结果/official_writer_20261017_152949_577923/record.json)
- advanced_json_cards
  - [writer原始记录](../../../../3-1/lizhuofan-curry/运行结果/official_writer_20261017_153104_166016/record.json)
  - [judge原始记录](../../../../3-1/lizhuofan-curry/运行结果/official_judge_20261017_153920_251926/record.json)
  - [模型记忆](../../../../3-1/lizhuofan-curry/运行结果/official_writer_20261017_153104_166016/memory.json)；[完整回答](../../../../3-1/lizhuofan-curry/运行结果/official_writer_20261017_153104_166016/answer.txt)
