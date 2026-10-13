# 运行完整实验

[返回 README](../README.md)

也可以在[一体化展示](../index.html)的“运行方法”页面查看三个操作步骤。展示页本身不执行算法。

完整实验需要 Linux、NVIDIA GPU、Python 3.11，以及自行准备的 JEV checkpoint、Qwen3 backbone、Qwen3.5-27B 和 Cloud-OpsBench。JEV checkpoint 需符合 `DecisionEngine` 的 `state_dict` 格式。展示实验使用了领域微调的排序 checkpoint，公开原模型不保证复现同样成绩。

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-advisor.txt
cp configs/local.example.json configs/local.json
```

编辑 `configs/local.json`，填写自己的模型、benchmark 路径和空闲 GPU；相对路径基于项目根目录。内存保护至少保留 50 GiB。然后准备运行：

```bash
python scripts/prepare_online.py --config configs/local.json --run online754
```

准备完成后，启动任务自己的 worker、LLM advisor 和在线协调流程：

```bash
tmux new-session -d -s jev-worker "python scripts/jev.py worker --run online754"
tmux new-session -d -s jev-advisor "python scripts/jev.py advisor --run online754 --advisor-max-model-len 262144 --advisor-gpu-memory-utilization 0.85 --advisor-max-num-seqs 1"
python src/guard_process.py --record runs/online754/pipeline_resources.json -- python scripts/online_pipeline.py --run online754
```

等待 worker 就绪、advisor 的 `/v1/models` 可访问后运行协调命令。它按“首答 → 保存 → 释放反馈 → LLM 提议 → 证据校验 → 下一题”推进。查看 `runs/online754/status.json` 可获得完成数、首答准确率和规则更新计数。协调流程中断时原样重复协调命令，仅接续未完成步骤，不重新执行已开始的诊断；若中断导致首答结果不明，会停止核查，不能偷偷重跑。

Advisor 由 vLLM 一次加载并常驻，逐题请求不会重新加载模型。示例使用 256K 上下文和单请求并发；服务启动时会核验 KV cache 容量，显存不足时需为新实验选择能安全运行的上下文上限，不能只修改宣称的长度。

全部完成后生成 `runs/online754/online_summary.json`，核对 754 个唯一首答、每题一次启动、反馈时序、Harness 版本链和输入哈希。协调流程随后停止任务自己的 worker/advisor，运行 `scripts/publish_online.py` 将实际首答准确率、逐题更新、方法介绍同步到 README 和前端；不会启动服务器前端。旧冻结对照流程保留在 `scripts/active_pipeline.py`，不要与在线协议混用。运行数据写入忽略版本管理的 `runs/`，不修改原模型或原 benchmark，也不需要定时任务。

完整审计通过后，为自己的新实验导出逐题展示详情并核验发布包：

```bash
python scripts/export_diagnostics.py --run runs/online754
python scripts/build_site.py
python scripts/package_audit.py --write
```

此步骤只从已保存的首答、工具输出及更新事件生成脱敏展示数据；不会重测题目。按需使用 `scripts/export_case_walkthroughs.py` 导出三个完整模块案例，详见该命令的 `--help`。

`build_site.py` 更新 `index.html` 和按题加载的静态展示资源，不修改已有首答。之后本地直接打开 `index.html`，或由仓库所有者启用 GitHub Pages。访客不用启动任何服务。
