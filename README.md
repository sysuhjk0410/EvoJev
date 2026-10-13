# EvoJev
### Evidence-Grounded Harness Evolution

**冻结的 JEV 引导 PUCT 采证，Harness 验证根因，LLM 将题后反馈提炼成只影响后续题的可执行经验。**

[展示](#一体化展示) · [方法](#方法) · [准确率](#总体准确率) · [运行方法](#运行方法)

## 一体化展示

**上传到 GitHub 后，本 README 会直接显示方法图、准确率与运行步骤，不需要部署。** 交互入口 `index.html` 将**结果、方法、运行方法**集成在同一页面，支持逐题轨迹、Harness 演进、中英切换与亮暗主题。

GitHub 仓库首页自动显示 README，但不能运行交互 HTML。按 `.gitignore` 上传发布文件到仓库根目录，不上传 `runs/`、`.cache/`、`models/`、`data/` 和本地配置。然后在 **Settings → Pages → Build and deployment → Source → Deploy from a branch** 选择上传分支（`main` 或 `master`）及 **/(root)**，点击 **Save**。只需启用一次，GitHub 自动托管展示，后续提交到该分支自动更新。部署完成后使用 Pages 提供的网站链接，可放在 About。无需手动启动服务器、Python 或模型。本项目没有代为上传或发布。[Pages 官方说明](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site)。

## 方法

![EvoJev 方法流程](workflow.png)

**诊断：** 公开问题 → 来源绑定证据 → JEV 候选排序 + PUCT 选择检查 → Harness 正反证校验 → 锁定首答。

**演进：** 首答保存 → 释放本题反馈 → LLM 提议通用规则 → 历史证据校验 → 下一题生效。JEV 权重不变，每题最多 72 次实际调用。不因反馈重答旧题。

[模块输入输出](docs/methodology.md) · [三个完整案例](docs/case_walkthroughs.json)

## 总体准确率

**454 / 754 = 60.21%。** 对象与原因必须同时精确正确，异常或缺失输出计错。754 个唯一首答，48 次准入更新，60 条最终规则。80% 目标未达到。

这是逐题首答成绩，不是用最终 Harness 回答旧题的成绩，也不是项目级未见基准成绩。本项目此前使用过该公开 benchmark。

## 运行方法

需要 Linux、NVIDIA GPU、Python 3.11，以及自行准备的 JEV checkpoint、Qwen3-0.6B、Qwen3.5-27B 和 Cloud-OpsBench。主机可用内存至少保留 50 GiB。展示成绩使用领域微调 checkpoint，公开原模型不保证复现同样成绩。

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-advisor.txt
cp configs/local.example.json configs/local.json
```

填写 `configs/local.json` 中自己的模型、数据路径与空闲 GPU。以下运行的是诊断算法，不是前端。

```bash
python scripts/prepare_online.py --config configs/local.json --run online754
tmux new-session -d -s jev-worker "python scripts/jev.py worker --run online754"
tmux new-session -d -s jev-advisor "python scripts/jev.py advisor --run online754 --advisor-max-model-len 262144 --advisor-gpu-memory-utilization 0.85 --advisor-max-num-seqs 1"
```

等待 worker 就绪、advisor 可用。示例 advisor 使用 256K 上下文，须按显存容量核验，JEV 不使用此上下文参数。

```bash
python src/guard_process.py --record runs/online754/pipeline_resources.json -- python scripts/online_pipeline.py --run online754
```

进度见 `runs/online754/status.json`，最终统计见 `online_summary.json`。每题只诊断一次，反馈仅用于后续题。中断后重复协调命令可接续，不重测已完成题。全部完成后更新静态展示。

```bash
python scripts/export_diagnostics.py --run runs/online754
python scripts/build_site.py
python scripts/package_audit.py --write
```

步骤与注意事项均在本页。只使用自己的空闲 GPU，原模型与 benchmark 只读。核对 754 个唯一首答、每题一次启动、反馈时序、Harness 版本链和输入哈希。首答不明时停止核查，不能重测或覆盖已有首答。

## 引用

[JEV](https://huggingface.co/aimeigaoshou/agent-jev) · [Qwen3-0.6B](https://huggingface.co/Qwen/Qwen3-0.6B) · [Qwen3.5-27B](https://huggingface.co/Qwen/Qwen3.5-27B) · [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) · [Cloud-OpsBench](https://github.com/LLM4Ops/Cloud-OpsBench)

[CITATIONS.bib](CITATIONS.bib) · [第三方许可](THIRD_PARTY_NOTICES.md)。不附模型或完整 benchmark。本项目不是上游官方实现。
