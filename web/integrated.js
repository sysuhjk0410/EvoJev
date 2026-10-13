'use strict';
(() => {
  const tabs = document.createElement('nav');
  tabs.id = 'results-tabs';
  tabs.className = 'result-tabs';
  tabs.setAttribute('aria-label', 'Result views');
  for (const id of ['overview', 'evolution', 'cases', 'knowledge', 'benchmark']) {
    const button = document.querySelector('.nav[data-view="' + id + '"]');
    if (button) tabs.append(button);
  }
  document.querySelector('main').prepend(tabs);
  const navigation = document.querySelector('aside nav');
  const results = document.createElement('button');
  results.className = 'main-entry active';
  results.innerHTML = '<i data-lucide="chart-no-axes-combined"></i><span>Results</span>';
  results.onclick = () => view('overview');
  navigation.prepend(results);
  const protocol = $('protocol');
  const legacy = protocol.querySelector('.method-surface');
  legacy.classList.add('legacy-method');
  protocol.querySelector('.section-heading h1').textContent = 'Evidence. Decision. Future experience.';
  protocol.querySelector('.section-heading .muted').textContent = 'Frozen JEV + PUCT + executable Harness. The LLM improves future cases only.';
  protocol.querySelector('.section-heading .header-actions')?.remove();
  const method = document.createElement('iframe');
  method.className = 'integrated-method';
  method.title = 'Method modules and real input-output examples';
  method.src = new URL('README.html?embed=1', document.baseURI).href;
  protocol.insertBefore(method, legacy);
  const run = document.createElement('section');
  run.id = 'runbook';
  run.className = 'view';
  document.querySelector('main footer').before(run);
  const runButton = document.createElement('button');
  runButton.className = 'nav';
  runButton.dataset.view = 'runbook';
  runButton.innerHTML = '<i data-lucide="terminal"></i><span>Run method</span><small>03</small>';
  runButton.onclick = () => view('runbook');
  navigation.append(runButton);
  const install = 'python3.11 -m venv .venv\nsource .venv/bin/activate\npip install -r requirements.txt -r requirements-advisor.txt\ncp configs/local.example.json configs/local.json';
  const config = '{\n  "benchmark_root": "data/Cloud-OpsBench",\n  "jev_checkpoint": "models/agentjev.pt",\n  "jev_backbone": "models/Qwen3-0.6B",\n  "advisor_model": "models/Qwen3.5-27B",\n  "jev_gpus": "0",\n  "advisor_gpus": "1,2",\n  "advisor_tensor_parallel": 2,\n  "mem_available_min_gib": 50\n}';
  const commands = 'python scripts/prepare_online.py --config configs/local.json --run online754\ntmux new-session -d -s jev-worker "python scripts/jev.py worker --run online754"\ntmux new-session -d -s jev-advisor "python scripts/jev.py advisor --run online754 --advisor-max-model-len 262144 --advisor-gpu-memory-utilization 0.85 --advisor-max-num-seqs 1"\npython src/guard_process.py --record runs/online754/pipeline_resources.json -- python scripts/online_pipeline.py --run online754';
  const finish = 'python scripts/export_diagnostics.py --run runs/online754\npython scripts/build_site.py\npython scripts/package_audit.py --write';
  const text = {
    zh: {
      title:'运行方法，不是部署前端。', lead:'在 Linux GPU 机器上跑一次完整的在线诊断与 Harness 演进。展示页只读取已完成记录，不执行模型。',
      facts:['Linux + Python 3.11','NVIDIA GPU','至少保留 50 GiB 主机内存'],
      one:'准备依赖与配置。', oneCopy:'在项目根目录执行命令。自行准备 AgentJev checkpoint、Qwen3-0.6B、Qwen3.5-27B 和 Cloud-OpsBench，再把自己的路径与空闲 GPU 填入 configs/local.json。相对路径以项目根目录为准。',
      configLabel:'需要填写的配置', checkpoint:'JEV checkpoint 需要符合 DecisionEngine 的 state_dict 格式。本次成绩来自领域微调 checkpoint，公开原模型不保证复现相同准确率。',
      two:'启动在线流程。', twoCopy:'先准备数据，再启动 JEV worker 和常驻 vLLM advisor。协调器等待二者就绪，按“诊断 → 锁定首答 → 反馈 → 更新 → 下一题”执行。',
      context:'256K 是 advisor 服务配置，不是 JEV 上下文。vLLM 会检查 KV cache 容量。如果自己的 GPU 无法容纳，应在新实验启动前选择可用上限。',
      three:'检查结果并更新展示。', threeCopy:'进度在 runs/online754/status.json。结束后查看 online_summary.json，再执行下方命令导出新展示。对象与原因必须同时正确，异常计错。',
      resume:'如何接续中断', resumeCopy:'重复同一条协调命令，只接续未完成步骤。已经开始但首答不明的诊断会停下核查，不会自动重测。已有首答不可覆盖。',
      notes:'运行注意事项', cautions:['只使用自己的空闲 GPU。主机 MemAvailable 至少保留 50 GiB，原模型和 benchmark 只读。','JEV 权重冻结。先锁定本题首答，再释放反馈更新 Harness，更新只影响后续题。','核对 754 个唯一首答、每题一次启动、反馈时序、Harness 版本链和输入哈希。导出展示不会重测题目。','展示页不执行模型。运行诊断需要 GPU，访问 GitHub Pages 展示不需要启动任何服务。'],
      result:'结果', method:'方法', run:'运行方法',
      methodTitle:'证据、决策与未来经验。', methodLead:'冻结的 JEV + PUCT + 可执行 Harness。LLM 只改进后续题。'
    },
    en: {
      title:'Run the method, not a web server.', lead:'Run online diagnosis and Harness evolution on a Linux GPU machine. This presentation only reads completed records and performs no inference.',
      facts:['Linux + Python 3.11','NVIDIA GPU','Keep at least 50 GiB host memory available'],
      one:'Prepare dependencies and configuration.', oneCopy:'Run commands from the project root. Prepare an AgentJev checkpoint, Qwen3-0.6B, Qwen3.5-27B and Cloud-OpsBench. Enter your paths and available GPU IDs in configs/local.json. Relative paths resolve from the project root.',
      configLabel:'Configuration to fill in', checkpoint:'The JEV checkpoint must match DecisionEngine state_dict. The reported score used a domain-finetuned checkpoint. The public model does not guarantee the same accuracy.',
      two:'Start the online pipeline.', twoCopy:'Prepare the run, then start the JEV worker and persistent vLLM advisor. The coordinator waits for both and executes diagnosis → commit → feedback → update → next case.',
      context:'256K configures the advisor, not JEV. vLLM validates KV cache capacity. Select a supported limit before starting a new run if your GPUs cannot accommodate it.',
      three:'Audit results and refresh the presentation.', threeCopy:'Progress is in runs/online754/status.json. Review online_summary.json after completion, then export the new presentation with the commands below. Both object and cause must match. Errors count wrong.',
      resume:'Resume an interrupted run', resumeCopy:'Repeat the same coordinator command to continue unfinished steps only. An ambiguous started diagnosis stops for inspection instead of being retaken. Existing first answers cannot be replaced.',
      notes:'Operational notes', cautions:['Use only your available GPUs. Keep MemAvailable at or above 50 GiB. Original models and benchmark are read-only.','JEV weights stay frozen. Commit the first answer before releasing feedback. Harness updates affect later cases only.','Audit 754 unique first answers, one diagnosis start per case, feedback ordering, Harness versions and input hashes. Presentation export never retakes a case.','This page performs no inference. Diagnosis requires GPUs. Visiting the GitHub Pages presentation requires no server startup.'],
      result:'Results', method:'Method', run:'Run method',
      methodTitle:'Evidence. Decision. Future experience.', methodLead:'Frozen JEV + PUCT + executable Harness. The LLM improves future cases only.'
    }
  };
  function preferences() {
    const zh = document.documentElement.lang === 'zh-CN';
    const words = text[zh?'zh':'en'];
    results.querySelector('span').textContent = words.result;
    navigation.querySelector('[data-view=protocol] span').textContent = words.method;
    runButton.querySelector('span').textContent = words.run;
    protocol.querySelector('.section-heading h1').textContent = words.methodTitle;
    protocol.querySelector('.section-heading .muted').textContent = words.methodLead;
    run.innerHTML = '<div class="section-heading"><div><div class="eyebrow">REPRODUCE / ONLINE DIAGNOSIS</div><h1>' + words.title + '</h1><p class="runbook-lead">' + words.lead + '</p></div></div>' +
      '<div class="runbook-facts">' + words.facts.map((fact,i)=>'<span><i data-lucide="'+['terminal','cpu','shield-check'][i]+'"></i>'+fact+'</span>').join('') + '</div>' +
      '<article class="run-step"><span>01</span><div><h2>'+words.one+'</h2><p>'+words.oneCopy+'</p><pre>'+esc(install)+'</pre><h3>'+words.configLabel+'</h3><pre>'+esc(config)+'</pre><p class="caption">'+words.checkpoint+'</p></div></article>' +
      '<article class="run-step"><span>02</span><div><h2>'+words.two+'</h2><p>'+words.twoCopy+'</p><pre>'+esc(commands)+'</pre><p class="caption">'+words.context+'</p></div></article>' +
      '<article class="run-step"><span>03</span><div><h2>'+words.three+'</h2><p>'+words.threeCopy+'</p><pre>'+esc(finish)+'</pre><h3>'+words.resume+'</h3><p>'+words.resumeCopy+'</p></div></article>' +
      '<section class="run-notes"><h2>'+words.notes+'</h2><ul>'+words.cautions.map(note=>'<li>'+esc(note)+'</li>').join('')+'</ul></section>';
    method.contentWindow?.postMessage({type:'evojev-preferences',language:zh?'zh':'en',theme:document.documentElement.dataset.theme||'light'}, '*');
    icons();
  }
  method.addEventListener('load', preferences);
  window.addEventListener('evojev-preferences', preferences);
  window.addEventListener('message', event => {
    if (event.source !== method.contentWindow || event.data?.type !== 'evojev-method-size') return;
    const height = Number(event.data.height);
    if (Number.isFinite(height) && height >= 200 && height <= 6000) method.style.height = Math.ceil(height) + 'px';
  });
  const oldView = view;
  view = function(id) {
    oldView(id);
    tabs.hidden = id === 'protocol' || id === 'runbook';
    results.classList.toggle('active', !tabs.hidden);
    if (id === 'protocol') preferences();
    if (id === 'evolution') renderEvolution();
  };
  navigation.querySelectorAll('small').forEach(element=>element.remove());
  preferences();
  view('overview');
})();
