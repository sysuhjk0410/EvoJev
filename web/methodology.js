'use strict';
(() => {
  const pair = (zh, en) => ({zh, en});
  const embedded = new URLSearchParams(location.search).get('embed') === '1';
  document.body.classList.toggle('embedded', embedded);
  const stages = [
    {
      icon: 'file-question',
      title: pair('接收公开问题', 'Receive the public task'),
      short: pair('公开问题', 'Public input'),
      principle: pair('求解器只收到公开问题、合法候选和已准入的历史 Harness。当前题的正确答案不进入诊断模块。', 'The solver receives a public task, valid candidates and the previously admitted Harness. The current answer is not an input.'),
      example: pair('这是服务可用性异常，不是“worker-01 的 containerd 故障”这样已经带有答案的问题。', 'The task reports an availability disruption. It does not disclose a containerd fault on worker-01.'),
      handoff: pair('问题、合法对象目录和 H82 交给证据采集模块。', 'The task, object catalog and H82 go to evidence acquisition.'),
      input: pair('{"query": "Service Availability Disruption.",\n "namespace": "boutique"}', '{"query": "Service Availability Disruption.",\n "namespace": "boutique"}'),
      output: pair('问题：服务可用性异常。\n当前 Harness：H82。\n合法候选节选：\n  app/frontend\n  app/checkoutservice\n  node/worker-01\n候选目录不标注本题正确答案。', 'Task: service availability disruption.\nCurrent Harness: H82.\nCandidate catalog excerpt:\n  app/frontend\n  app/checkoutservice\n  node/worker-01\nThe catalog does not identify the correct answer.')
    },
    {
      icon: 'database',
      title: pair('采集并绑定证据', 'Acquire source-bound evidence'),
      short: pair('绑定证据', 'Evidence'),
      principle: pair('工具读取资源、告警、日志等快照。每条观察都记录来源和实际对象，不能把一个节点的错误归给另一个节点。', 'Tools read resource, alert and log snapshots. Each observation retains its source and actual owner. Evidence from different nodes cannot be joined as one cause.'),
      example: pair('节点 NotReady 说明它值得检查，但不能单独证明 containerd、kubelet 或网络中的哪个出了问题。', 'NotReady makes the node worth inspecting. It does not distinguish containerd, kubelet or network failures.'),
      handoff: pair('带证据编号的观察交给 JEV 和搜索模块。', 'Observations with source IDs go to JEV and search.'),
      input: pair('GetResources\n  resource_type: nodes\n  namespace: boutique\n  name: ""', 'GetResources\n  resource_type: nodes\n  namespace: boutique\n  name: ""'),
      output: pair('证据：s2l2。\n归属：node/worker-01。\n原始输出节选：\nworker-01   NotReady   node   143d   v1.31.2', 'Source: s2l2.\nOwner: node/worker-01.\nOutput excerpt:\nworker-01   NotReady   node   143d   v1.31.2')
    },
    {
      icon: 'list-ordered',
      title: pair('JEV 给候选排序', 'JEV ranks the candidates'),
      short: pair('JEV 排序', 'JEV ranking'),
      principle: pair('冻结的分类模型根据当前问题和已获得证据给候选排序。分数帮助安排检查优先级，不等于根因正确率。', 'The frozen classifier ranks options from the task and acquired evidence. Scores set inspection priorities. They are not calibrated diagnosis accuracy.'),
      example: pair('worker-01 排在前面，所以更值得查节点。frontend 的 Pod 异常仍可能只是下游影响，不能直接当根因。', 'worker-01 ranks first, favoring node checks. An abnormal frontend Pod may still be a downstream effect.'),
      handoff: pair('对象与检查动作的排序分数交给树搜索。', 'Owner and action ranking scores guide tree search.'),
      input: pair('问题：服务可用性异常。\n当前证据：节点 NotReady，多个 Pod 启动异常。\n候选：节点与应用对象。', 'Task: service availability disruption.\nEvidence: a NotReady node and startup failures.\nOptions: node and application owners.'),
      output: pair('轨迹中记录的对象分数节选：\nnode/worker-01       0.744\napp/frontend         0.125\napp/checkoutservice  0.092\n数值已四舍五入，不是根因正确率。', 'Recorded owner scores, rounded:\nnode/worker-01       0.744\napp/frontend         0.125\napp/checkoutservice  0.092\nThese are ranking scores, not accuracy.')
    },
    {
      icon: 'git-fork',
      title: pair('PUCT 选择下一次检查', 'PUCT selects the next check'),
      short: pair('PUCT 搜索', 'PUCT search'),
      principle: pair('树的分支是工具动作。搜索结合 JEV 优先级、历史经验和覆盖收益，平衡利用与探索。执行选中的检查，获得新证据后再规划。', 'Branches represent tool actions. Search combines JEV priors, past experience and coverage utility to balance exploitation and exploration. Only the selected action is executed, then search replans.'),
      example: pair('本次选择查 containerd。后续再查 kubelet，区分“运行时停止”和“kubelet 本身停止”。这不是反复让模型猜答案。', 'The selected check inspects containerd. A later kubelet check distinguishes runtime failure from kubelet failure. Search does not repeatedly generate answers.'),
      handoff: pair('实际工具输出返回证据模块，再交给 Harness。', 'Actual tool output returns to evidence binding and Harness checks.'),
      input: pair('轨迹步骤 32 前的节选：\n已有节点与服务证据。\n剩余预算：40 次实际调用。\n历史经验：此前 384 个健康案例。\n每次规划：96 次代理模拟，视野为 3 次调用成本。', 'Excerpt before trace step 32:\nNode and service evidence already acquired.\nRemaining budget: 40 actual calls.\nExperience: 384 prior healthy cases.\nPlanning: 96 surrogate simulations, horizon 3 call costs.'),
      output: pair('CheckNodeServiceStatus\n  node_name: worker-01\n  service_name: containerd\n实际返回：Active: inactive (dead)。\n模拟不读取未来工具输出或答案。\n每题实际调用上限为 72 次。', 'CheckNodeServiceStatus\n  node_name: worker-01\n  service_name: containerd\nActual result: Active: inactive (dead).\nSimulations use no future outputs or labels.\nActual per-case call cap: 72.')
    },
    {
      icon: 'filter',
      title: pair('Harness 验证根因', 'Harness verifies the cause'),
      short: pair('根因验证', 'Harness'),
      principle: pair('规则检查同一对象的正向证据和实际反证。完整证据约束根因候选。没有完整证据时使用经验或 JEV 后备候选，不伪造证明。', 'Executable rules require source-consistent positive evidence and check observed contradictions. Witnesses constrain candidates. Without a complete witness, experience or JEV fallback candidates are used.'),
      example: pair('containerd 已停止，而 kubelet 仍运行并报告 runtime socket 不存在。直接故障在 containerd，多服务启动失败是影响表现。', 'containerd is stopped while kubelet is running and reports a missing runtime socket. containerd is the direct failure. Application startup errors are effects.'),
      handoff: pair('证据支持的对象与原因对交给首答保存模块。', 'The supported object-cause pair goes to first-answer storage.'),
      input: pair('同一节点 worker-01：\ns32l4    containerd: inactive (dead)。\ns35l4    kubelet: active (running)。\ns35l14   kubelet 无法连接 containerd socket，\n         错误为 no such file or directory。', 'Same node, worker-01:\ns32l4    containerd: inactive (dead).\ns35l4    kubelet: active (running).\ns35l14   kubelet cannot connect to containerd socket,\n         with no such file or directory.'),
      output: pair('{"fault_object": "node/worker-01",\n "root_cause": "containerd_unavailable"}\n\n已有规则支持的证据：s32l4、s35l14。\n本题过滤后只剩这一对象与原因对。', '{"fault_object": "node/worker-01",\n "root_cause": "containerd_unavailable"}\n\nExisting rules cite s32l4 and s35l14.\nOnly this object-cause pair remains.')
    },
    {
      icon: 'lock-keyhole',
      title: pair('锁定不可覆盖的首答', 'Lock the first answer'),
      short: pair('首答锁定', 'First answer'),
      principle: pair('预测、工具轨迹、版本和哈希先保存，再释放本题确认反馈。后续更新不能改写这次答案，也不能回头重测。', 'Persist the prediction, tool trace, version and hashes before releasing feedback. Later updates cannot replace this answer or retake the case.'),
      example: pair('如果这次答错，仍按错题计分。下一版 Harness 可以学到经验，但不能把本题改成正确。', 'A wrong first answer stays wrong in scoring. The next Harness may learn from it, but cannot retroactively repair its score.'),
      handoff: pair('保存完成后，轨迹和确认反馈才可交给 LLM。', 'Only after commit may the trace and feedback reach the LLM.'),
      input: pair('待保存预测：\nnode/worker-01 | containerd_unavailable\n实际工具轨迹、H82 和请求哈希。', 'Prediction to persist:\nnode/worker-01 | containerd_unavailable\nActual trace, H82 and request hashes.'),
      output: pair('1. 保存首答和轨迹。\n2. 释放本题确认反馈。\n3. 确认对象与原因均与首答一致。\n4. 将已完成记录交给题后顾问。', '1. Persist the first answer and trace.\n2. Release this completed case\'s feedback.\n3. Both confirmed fields match the answer.\n4. Send the completed record to the advisor.')
    },
    {
      icon: 'brain-circuit',
      title: pair('LLM 提炼通用规则', 'LLM proposes a reusable rule'),
      short: pair('LLM 提炼', 'LLM proposal'),
      principle: pair('Qwen3.5-27B 在题后提议一条可执行规则，或者返回 no_update。它使用已采集证据和确认反馈，不能按具体节点名或 case 编号查答案。', 'Qwen3.5-27B proposes one executable rule after completion, or no_update. It uses acquired evidence and confirmed feedback, not incident-ID or node-name answer lookups.'),
      example: pair('经验被写成“同一节点的 containerd 停止且 kubelet 报告 socket 不存在”，而不是“worker-01 就是答案”。', 'The rule encodes stopped containerd plus a kubelet missing-socket error on the same node. It does not encode worker-01 as the answer.'),
      handoff: pair('规则提议交给准入校验，还不能直接生效。', 'The proposal goes to admission checks. It is not active yet.'),
      input: pair('已锁定首答与工具证据。\n题后确认原因：containerd_unavailable。\n已准入规则与合法原因目录。\n当前题诊断已经结束。', 'Committed answer and acquired evidence.\nConfirmed cause: containerd_unavailable.\nAdmitted rules and valid cause catalog.\nThe diagnosis is already complete.'),
      output: pair('适用对象：任意节点。\n正向条件：containerd 停止，并且同节点\n          kubelet 日志报告 containerd socket 不存在。\n反向条件：实际观察到 kubelet 也停止。\n支持原因：containerd_unavailable。\n规则不包含 worker-01 或 case 编号。', 'Target: any node.\nPositive: stopped containerd AND a kubelet\n          missing-containerd-socket error on the same node.\nNegative: observed stopped kubelet.\nCause: containerd_unavailable.\nNo worker-01 or incident-ID lookup.')
    },
    {
      icon: 'shield-check',
      title: pair('校验后，只向未来演进', 'Admit updates for future cases'),
      short: pair('未来生效', 'Admission'),
      principle: pair('先检查规则格式、引用和对象归属，再匹配已完成案例的缓存证据。至少两个案例支持，见证精度不低于 95%，且不能在原本答对的历史题上产生错误见证。', 'Check syntax, citations and ownership, then match cached completed-case evidence. Require at least two supporting cases, 95% witness precision and no wrong witness on an originally correct case.'),
      example: pair('这条提议获 8 个案例支持，见证精度为 100%。H82 更新为 H83，只从第 390 题起使用。历史匹配不重新诊断旧题。', 'This proposal has eight supporting cases and 100% witness precision. H82 becomes H83 for position 390 onward. Historical matching does not re-diagnose cases.'),
      handoff: pair('新规则与历史经验交给下一题，JEV 权重不变。', 'Future cases receive updated rules and experience. JEV weights stay frozen.'),
      input: pair('当前提议规则。\n截至本题已完成的 389 份历史记录。\n原始首答和确认反馈。\n不调用工具，不重新执行 JEV。', 'The proposed rule.\n389 completed historical records.\nOriginal answers and confirmed feedback.\nNo tool execution or JEV re-run.'),
      output: pair('支持案例：8。\n见证精度：100%。\n原本正确题上的错误见证：0。\n准入：accepted。\n版本：H82 → H83。\n生效范围：第 390 题及以后。', 'Supporting cases: 8.\nWitness precision: 100%.\nWrong witnesses on correct cases: 0.\nDecision: accepted.\nVersion: H82 → H83.\nApplies to stream position 390 onward.')
    }
  ];
  const copy = {
    zh: {
      'brand-detail':'方法与案例','page-title':'从一题诊断，理解整套方法。',
      'method-summary':'冻结的 JEV 引导树搜索获取证据，Harness 验证根因，大模型在首答保存后提炼可靠经验，只改进后续题。',
      'workflow-diagnosis':'冻结的 JEV 为根因候选和检查动作评分，PUCT 树搜索在固定预算内获取证据，Harness 根据来源一致的证据约束诊断。',
      'workflow-evolution':'每题先保存唯一首答并评分，再由 Qwen3.5-27B 提议通用规则，经历史证据审核通过后写入 Harness，只用于后续题目。',
      'workflow-experience':'独立的 TF-IDF 与逻辑回归模型每累计完成八题，用全部已完成且流程正常的案例重新拟合，辅助 JEV 排序候选根因，并指导 PUCT 树搜索选择更有区分力的检查，JEV 与 LLM 权重不变。',
      'case-position':'第 389 题','source-caption':'真实轨迹节选 · 非重新推理','playback-caption':'模块流程',
      'diagnosis-label':'当前题诊断','evolution-label':'题后演进','diagram-title':'证据与决策路径',
      'legend-diagnosis':'当前题','legend-evolution':'后续题','diagram-caption':'动画表示模块衔接，不是实际运行时序。',
      'input-label':'输入','output-label':'输出','guard-title':'首答先保存，反馈后释放。',
      'guard-copy':'第 389 题用 H82 作答。H83 只用于第 390 题起，不能修改这一题的答案。',
      'version-before':'本题','version-future':'后续题','result-caption':'全量在线首答准确率',
      'result-count':'454 / 754。对象与原因都正确才计分。',
      'result-boundary':'每题诊断一次。异常与缺失输出计错。公开基准此前已被本项目使用，这不是未见基准成绩。80% 目标未达到。',
      'footer-note':'示例省略非关键字段。八个模块仍保留实际的数据与反馈边界。',
      'text-link':'文字版','case-link':'完整案例', previous:'上一步', next:'下一步', reset:'回到开始',
      'start-title':'在自己的电脑上启动。', 'start-copy':'项目根目录执行下方命令。展示系统只需 Python 3.9+，无需模型或 GPU。', 'run-link':'算法运行指南',
      play:'播放流程', pause:'暂停流程', results:'结果展示', dark:'切换深色', light:'切换浅色',
      diagnosis:'诊断阶段', evolution:'题后演进', canvas:'方法流程图', seek:'当前模块', nav:'方法模块',
      barrier:'先保存首答，再释放反馈。', future:'仅向未来生效。',
      'memory-title':'两种更新频率与独立评分模型。',
      'memory-copy':'本例在第 389 题后更新规则，历史评分模型仍来自第 384 题结束时的刷新。',
      'memory-rule-title':'规则：每题',
      'memory-rule-definition':'每完成一题，LLM 提议通用规则，审核通过后更新 Harness，从下一题起生效。',
      'memory-rule-example':'例如，第 389 题用 H82 诊断，题后规则获准形成 H83，第 390 题开始使用 H83。',
      'memory-refresh-title':'经验：每八题',
      'memory-refresh-definition':'每累计完成八题，系统用截至当时全部流程正常的已完成案例重新拟合 TF-IDF 与逻辑回归模型，原首答答错的案例也可参与。',
      'memory-refresh-example':'例如，第 8 题后学习第 1～8 题，第 9～16 题沿用这份经验，第 16 题结束后学习第 1～16 题，供第 17 题起使用。',
      'memory-model-title':'模型：独立评分',
      'memory-model-definition':'TF-IDF 与逻辑回归辅助评分模型独立于 JEV 和 LLM，帮助 JEV 诊断系统排序候选根因，并指导 PUCT 树搜索优先选择更能区分这些根因的检查。',
      'memory-model-example':'例如，若历史案例中“runtime socket 不存在”常与 containerd 故障关联，它可提高该候选的评分，帮助树搜索优先检查 containerd 的运行状态。'
    },
    en: {
      'brand-detail':'Method & case','page-title':'One incident. The complete method.',
      'method-summary':'Frozen JEV guides evidence search, executable Harness checks validate causes, and an LLM distills verified post-case experience for future cases only.',
      'workflow-diagnosis':'Frozen JEV scores candidate causes and diagnostic actions, budgeted PUCT search acquires evidence, and Harness constrains the diagnosis with source-consistent observations.',
      'workflow-evolution':'Each first answer is committed and scored before Qwen3.5-27B proposes reusable rules, which enter Harness after historical-evidence validation and apply only to subsequent cases.',
      'workflow-experience':'Every eight completed cases, an independent TF-IDF and logistic-regression model is refitted on all completed cases with healthy execution to help JEV rank candidate causes and guide PUCT toward more discriminative checks, without changing JEV or LLM weights.',
      'case-position':'Stream position 389','source-caption':'Recorded excerpts · no new inference','playback-caption':'Method flow',
      'diagnosis-label':'Current diagnosis','evolution-label':'Post-case evolution','diagram-title':'Evidence and decisions',
      'legend-diagnosis':'Current case','legend-evolution':'Future cases','diagram-caption':'Animation shows module connections, not execution timing.',
      'input-label':'Input','output-label':'Output','guard-title':'Commit first. Release feedback second.',
      'guard-copy':'Position 389 uses H82. H83 applies from position 390 onward and cannot change this answer.',
      'version-before':'Current','version-future':'Future','result-caption':'Full-stream first-answer accuracy',
      'result-count':'454 / 754. Both object and cause must match.',
      'result-boundary':'One diagnosis per case. Errors and missing outputs count wrong. This public benchmark was used earlier in the project. These are not unseen-benchmark results. The 80% target was not reached.',
      'footer-note':'Excerpts omit non-essential fields while retaining the actual evidence and feedback boundaries.',
      'text-link':'Text version','case-link':'Full case records', previous:'Previous step', next:'Next step', reset:'Back to start',
      'start-title':'Run on your own computer.', 'start-copy':'Run the command below from the project root. The presentation needs Python 3.9+ only, without models or a GPU.', 'run-link':'Algorithm run guide',
      play:'Play method', pause:'Pause method', results:'Results', dark:'Dark appearance', light:'Light appearance',
      diagnosis:'Diagnosis', evolution:'Post-case evolution', canvas:'Method flow diagram', seek:'Current module', nav:'Method modules',
      barrier:'Commit answer before feedback.', future:'Future cases only.',
      'memory-title':'Two update schedules and an independent scoring model.',
      'memory-copy':'Position 389 updates a rule while its experience still comes from the refresh after position 384.',
      'memory-rule-title':'Rules: every case',
      'memory-rule-definition':'After each case, the LLM proposes reusable rules and verified rules update Harness for the next case onward.',
      'memory-rule-example':'For example, position 389 uses H82 and its admitted rule creates H83, which applies from position 390.',
      'memory-refresh-title':'Experience: every eight',
      'memory-refresh-definition':'Every eight completed cases, TF-IDF and logistic regression are refitted on all completed cases with healthy execution, including incorrect first answers.',
      'memory-refresh-example':'For example, cases 1–8 train the model used for cases 9–16, then all cases 1–16 train its replacement for case 17 onward.',
      'memory-model-title':'Independent scoring',
      'memory-model-definition':'The auxiliary TF-IDF and logistic-regression model is independent of JEV and the LLM, helping the JEV diagnosis system rank candidate causes and guiding PUCT search toward checks that better distinguish those causes.',
      'memory-model-example':'For example, if missing runtime sockets often accompany containerd failures in history, it can raise that candidate’s score and guide search toward checking containerd status.'
    }
  };
  const $ = id => document.getElementById(id);
  let language='zh', theme='light', index=0, timer=null, frame=0, geometry=[], colors={};
  try {
    language=localStorage.getItem('evojev-method-language')==='en'?'en':'zh';
    theme=localStorage.getItem('evojev-theme')==='dark'?'dark':'light';
  } catch {}
  const reduced=matchMedia('(prefers-reduced-motion: reduce)');
  function label(id, text) { $(id).title=text; $(id).setAttribute('aria-label',text); }
  function render(animate=true) {
    const words=copy[language], stage=stages[index];
    document.documentElement.lang=language==='zh'?'zh-CN':'en';
    document.documentElement.dataset.theme=theme;
    document.body.dataset.theme=theme;
    document.title=language==='zh'?'EvoJev | 方法与案例':'EvoJev | Method & Case';
    $('workflow-image').alt=language==='zh'?'EvoJev 的证据驱动诊断与题后 Harness 演进流程':'EvoJev evidence-grounded diagnosis and post-case Harness evolution workflow';
    document.querySelector('meta[name="theme-color"]').content=theme==='dark'?'#151b1b':'#ffffff';
    for(const [id,value] of Object.entries(words)) if($(id)&&!['previous','next','reset','play'].includes(id)) $(id).textContent=value;
    $('stage-navigation').innerHTML=stages.map((s,i)=>'<button class="stage'+(i===index?' active':'')+'" data-index="'+i+'" aria-current="'+(i===index?'step':'false')+'"><i data-lucide="'+s.icon+'"></i><span><small>0'+(i+1)+'</small>'+s.short[language]+'</span></button>').join('');
    $('stage-navigation').setAttribute('aria-label',words.nav);
    $('position').textContent='0'+(index+1)+' / 08';
    $('seek').value=String(index);
    $('seek').setAttribute('aria-label',words.seek);
    $('module-number').textContent='0'+(index+1);
    $('module-plane').textContent=index<6?words.diagnosis:words.evolution;
    $('module-title').textContent=stage.title[language];
    $('module-principle').textContent=stage.principle[language];
    $('module-example').textContent=stage.example[language];
    $('module-handoff').textContent=stage.handoff[language];
    $('module-input').textContent=stage.input[language];
    $('module-output').textContent=stage.output[language];
    $('experience-note').hidden=false;
    $('version-after').style.opacity=index===7?'1':'.48';
    label('results-link',words.results);
    label('theme-toggle',theme==='light'?words.dark:words.light);
    $('theme-toggle').setAttribute('aria-checked',String(theme==='dark'));
    $('theme-toggle').innerHTML='<i data-lucide="'+(theme==='light'?'moon':'sun')+'"></i>';
    label('language-toggle',language==='zh'?'Switch to English':'切换中文');
    $('language-toggle').innerHTML='<i data-lucide="languages"></i><span>'+(language==='zh'?'中':'EN')+'</span>';
    for(const id of ['previous','next','reset']) label(id,words[id]);
    label('play',timer?words.pause:words.play);
    $('play').innerHTML='<i data-lucide="'+(timer?'pause':'play')+'"></i>';
    $('previous').disabled=index===0;
    $('next').disabled=index===7;
    $('method-canvas').setAttribute('aria-label',words.canvas);
    if(window.lucide) window.lucide.createIcons();
    if(animate&&!reduced.matches) {
      for(const el of [$('module-title'),$('module-principle'),$('module-input'),$('module-output')]) {
        el.classList.remove('refreshing');
        void el.offsetWidth;
        el.classList.add('refreshing');
      }
    }
    const styles=getComputedStyle(document.body);
    colors=Object.fromEntries(['bg','ink','muted','line','soft','teal','blue','coral','amber','grid'].map(k=>[k,styles.getPropertyValue('--'+k).trim()]));
    draw(performance.now());
  }
  function stop() { if(timer) clearInterval(timer); timer=null; }
  function select(next) { stop(); index=Math.max(0,Math.min(7,next)); render(); }
  $('stage-navigation').addEventListener('click',event=>{
    const button=event.target.closest('[data-index]');
    if(button) select(Number(button.dataset.index));
  });
  $('stage-navigation').addEventListener('keydown',event=>{
    if(!['ArrowLeft','ArrowRight'].includes(event.key)) return;
    event.preventDefault();
    select(index+(event.key==='ArrowRight'?1:-1));
    $('stage-navigation').querySelector('[data-index="'+index+'"]').focus();
  });
  $('seek').addEventListener('input',event=>select(Number(event.target.value)));
  $('previous').addEventListener('click',()=>select(index-1));
  $('next').addEventListener('click',()=>select(index+1));
  $('reset').addEventListener('click',()=>select(0));
  $('play').addEventListener('click',()=>{
    if(timer) { stop(); render(false); return; }
    if(index===7) index=0;
    timer=setInterval(()=>{
      index++;
      if(index===7) stop();
      render();
    },4800);
    render(false);
  });
  $('theme-toggle').addEventListener('click',()=>{
    theme=theme==='light'?'dark':'light';
    try{localStorage.setItem('evojev-theme',theme);}catch{}
    render(false);
  });
  $('language-toggle').addEventListener('click',()=>{
    language=language==='zh'?'en':'zh';
    try{localStorage.setItem('evojev-method-language',language);}catch{}
    render(false);
  });
  function round(ctx,x,y,w,h,r) {
    ctx.beginPath();ctx.roundRect(x,y,w,h,r);
  }
  function line(ctx,a,b,color,dashed=false) {
    ctx.strokeStyle=color;ctx.lineWidth=1.5;ctx.setLineDash(dashed?[4,5]:[]);
    ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);ctx.stroke();ctx.setLineDash([]);
    const angle=Math.atan2(b.y-a.y,b.x-a.x);
    ctx.beginPath();ctx.moveTo(b.x,b.y);
    ctx.lineTo(b.x-6*Math.cos(angle-.45),b.y-6*Math.sin(angle-.45));
    ctx.lineTo(b.x-6*Math.cos(angle+.45),b.y-6*Math.sin(angle+.45));
    ctx.closePath();ctx.fillStyle=color;ctx.fill();
  }
  function draw(time) {
    const canvas=$('method-canvas'), ctx=canvas.getContext('2d'), width=canvas.clientWidth, height=canvas.clientHeight;
    if(!width||!height) return;
    const ratio=Math.min(devicePixelRatio||1,2);
    if(canvas.width!==Math.round(width*ratio)||canvas.height!==Math.round(height*ratio)) {
      canvas.width=Math.round(width*ratio);canvas.height=Math.round(height*ratio);
    }
    ctx.setTransform(ratio,0,0,ratio,0,0);
    ctx.fillStyle=colors.soft;ctx.fillRect(0,0,width,height);
    ctx.strokeStyle=colors.grid;ctx.lineWidth=.6;
    for(let x=12;x<width;x+=24){ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,height);ctx.stroke();}
    for(let y=12;y<height;y+=24){ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(width,y);ctx.stroke();}
    const left=22,gap=38,nodeWidth=(width-2*left-gap)/2,nodeHeight=43;
    const ys=[31,94,157,height-72], xs=[left,left+nodeWidth+gap];
    const points=[[0,0],[1,0],[1,1],[0,1],[0,2],[1,2],[1,3],[0,3]];
    geometry=points.map(([x,y],i)=>({x:xs[x],y:ys[y],w:nodeWidth,h:nodeHeight,i}));
    const edges=[];
    for(let i=0;i<7;i++){
      const a=geometry[i],b=geometry[i+1],horizontal=a.y===b.y;
      const start=horizontal?{x:a.x+(b.x>a.x?a.w:0),y:a.y+a.h/2}:{x:a.x+a.w/2,y:a.y+a.h};
      const end=horizontal?{x:b.x+(b.x<a.x?b.w:0),y:b.y+b.h/2}:{x:b.x+b.w/2,y:b.y};
      const color=i<5?colors.teal:colors.blue;
      line(ctx,start,end,i<index?color:colors.line,i===5);
      edges.push({start,end,color});
    }
    const barrier=ys[2]+nodeHeight+21;
    ctx.strokeStyle=colors.blue;ctx.setLineDash([3,4]);ctx.beginPath();ctx.moveTo(13,barrier);ctx.lineTo(width-13,barrier);ctx.stroke();ctx.setLineDash([]);
    ctx.fillStyle=colors.soft;ctx.fillRect(width/2-111,barrier-9,222,18);
    ctx.fillStyle=colors.blue;ctx.font='11px system-ui';ctx.textAlign='center';ctx.fillText(copy[language].barrier,width/2,barrier+4);
    for(const node of geometry){
      const active=node.i===index,color=node.i<6?colors.teal:colors.blue;
      ctx.fillStyle=colors.bg;round(ctx,node.x,node.y,node.w,node.h,5);ctx.fill();
      ctx.strokeStyle=active?color:colors.line;ctx.lineWidth=active?1.8:1;ctx.stroke();
      if(active){ctx.globalAlpha=.07;ctx.fillStyle=color;round(ctx,node.x,node.y,node.w,node.h,5);ctx.fill();ctx.globalAlpha=1;}
      ctx.fillStyle=active?color:colors.muted;ctx.textAlign='left';ctx.font='11px ui-monospace,monospace';ctx.fillText('0'+(node.i+1),node.x+10,node.y+17);
      ctx.textAlign='center';ctx.font=(language==='zh'?'14':'12')+'px system-ui';ctx.fillStyle=active?color:colors.ink;
      ctx.fillText(stages[node.i].short[language],node.x+node.w/2+8,node.y+28);
    }
    if(index>0&&!reduced.matches){
      const edge=edges[index-1],t=(time%2000)/2000;
      const x=edge.start.x+(edge.end.x-edge.start.x)*t,y=edge.start.y+(edge.end.y-edge.start.y)*t;
      ctx.beginPath();ctx.arc(x,y,3.2,0,Math.PI*2);ctx.fillStyle=edge.color;ctx.fill();
    }
    ctx.font='11px system-ui';ctx.fillStyle=colors.blue;ctx.textAlign='center';ctx.fillText(copy[language].future,width/2,height-10);
  }
  $('method-canvas').addEventListener('click',event=>{
    const rect=event.currentTarget.getBoundingClientRect();
    const node=geometry.find(n=>event.clientX-rect.left>=n.x&&event.clientX-rect.left<=n.x+n.w&&event.clientY-rect.top>=n.y&&event.clientY-rect.top<=n.y+n.h);
    if(node) select(node.i);
  });
  $('method-canvas').addEventListener('mousemove',event=>{
    const rect=event.currentTarget.getBoundingClientRect();
    event.currentTarget.style.cursor=geometry.some(n=>event.clientX-rect.left>=n.x&&event.clientX-rect.left<=n.x+n.w&&event.clientY-rect.top>=n.y&&event.clientY-rect.top<=n.y+n.h)?'pointer':'default';
  });
  new ResizeObserver(()=>draw(performance.now())).observe($('method-canvas'));
  function tick(time) {
    if(!document.hidden&&!reduced.matches&&time-frame>40){draw(time);frame=time;}
    requestAnimationFrame(tick);
  }
  render(false);
  requestAnimationFrame(tick);
  window.addEventListener('pagehide',stop);
  if (embedded) {
    let lastHeight = 0;
    const resize = new ResizeObserver(() => {
      const height = Math.ceil(document.querySelector('main').getBoundingClientRect().height);
      if (height !== lastHeight) {
        lastHeight = height;
        parent.postMessage({type:'evojev-method-size',height}, '*');
      }
    });
    resize.observe(document.querySelector('main'));
    window.addEventListener('message',event => {
      if (event.source !== parent || event.data?.type !== 'evojev-preferences') return;
      language = event.data.language === 'zh' ? 'zh' : 'en';
      theme = event.data.theme === 'dark' ? 'dark' : 'light';
      render(false);
    });
  }
})();
