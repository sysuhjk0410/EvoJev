# EvoJev
### Evidence-Grounded Harness Evolution

[**打开交互系统**](https://sysuhjk0410.github.io/EvoJev/)

## 方法

**冻结的 JEV 引导 PUCT 采证，Harness 验证根因，LLM 将题后反馈提炼成只影响后续题的可执行经验。**

![EvoJev 方法流程](workflow.png)

**诊断。** 在 [Cloud-OpsBench](https://github.com/LLM4Ops/Cloud-OpsBench) 的只读观测上，[JEV](https://huggingface.co/aimeigaoshou/agent-jev) 为候选根因与检查动作评分，PUCT 树搜索在固定预算内采集证据。Harness 根据来源一致的正反证验证故障对象与原因，然后保存本题唯一首答。

**演进。** 首答锁定后释放反馈，[Qwen3.5-27B](https://huggingface.co/Qwen/Qwen3.5-27B) 提议可复用的证据规则。规则经历史证据核验后更新 Harness，只用于下一题及以后的诊断，不重答或改写旧结果。

**经验。** 每累计完成八题，用截至当时全部流程正常的已完成案例重新拟合 TF-IDF 与逻辑回归模型，辅助 JEV 排序候选根因，并指导 PUCT 优先选择更有区分力的检查。JEV 与 LLM 权重始终保持冻结。

[引用](CITATIONS.bib) · [第三方许可](THIRD_PARTY_NOTICES.md)
