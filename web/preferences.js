'use strict';
(() => {
  const chinese = {
    'EVIDENCE-GROUNDED':'证据驱动', 'HARNESS EVOLUTION':'Harness 自进化',
    'RESEARCH OBSERVATORY':'研究观测台', 'MODEL ROLES':'模型分工',
    'SINGLE-PASS STUDY':'单遍在线研究', 'FROZEN STUDY':'冻结实验',
    'Results':'总览', 'Evolution':'演进', 'Harness':'Harness', 'Cases':'案例',
    'Method':'方法', 'Benchmark':'基准', 'Final results':'最终结果',
    'Harness evolution':'Harness 演进', 'Final Harness':'最终 Harness',
    'Case results':'逐题结果', 'Study methodology':'研究方法',
    'Benchmark introduction':'基准介绍', 'Refresh final results':'刷新最终结果',
    'Verified single-pass results':'已验证的单遍结果',
    'Verified final results':'已验证的最终结果', 'Final verification':'最终验证',
    'Final results not yet published':'最终结果尚未发布',
    'Result archive unavailable':'结果档案暂不可用',
    'Final result archive':'最终结果档案',
    'incidents · one online method':'故障案例 · 单一在线方法',
    'Evidence-conditioned ranking':'基于证据的候选排序',
    'Post-case rule proposals':'题后规则提议', 'First-answer integrity':'首答完整性',
    'Frozen verification':'冻结验证',
    'CLOUD-OPSBENCH / FINAL VERIFICATION':'CLOUD-OPSBENCH / 最终验证',
    'Evidence to experience.':'从证据到经验。',
    'EvoJev: Evidence-Grounded Harness Evolution for Root Cause Analysis':'EvoJev：面向根因分析的证据驱动 Harness 自进化',
    'Prequential first-answer accuracy':'在线逐题首答准确率',
    'Exact object AND cause · no retakes':'对象与原因均正确 · 无重测',
    'Harness versions':'Harness 版本数', 'Executable experience':'可执行经验',
    'Immutable first answers':'不可覆盖的首答', 'One diagnosis per case':'每题仅诊断一次',
    'Cumulative first-answer accuracy':'累计首答准确率', 'FIXED CASE ORDER':'固定案例顺序',
    'Prequential cumulative first-answer accuracy':'在线累计首答准确率',
    'Chronological first answers, scored before each post-case update; no retrospective replacements.':'按时间顺序记录首答，在每次题后更新之前评分；不回溯替换结果。',
    'Single-pass outcome':'单遍诊断结果', 'Exact object + cause':'对象与原因联合正确',
    'Correct':'正确', 'Incorrect':'错误', 'correct':'正确', 'incorrect':'错误',
    '754 unique starts · no retakes · audit passed':'754 次唯一诊断启动 · 无重测 · 审计通过',
    'Single-pass evolution':'单遍演进统计',
    'CHRONOLOGICAL FIRST ANSWERS':'按时间顺序的首答',
    'Stream positions':'序列位置', 'First correct':'首答正确数', 'Accuracy':'准确率',
    'Rule updates':'规则更新次数', 'Harness version':'Harness 版本',
    'Each score is the original answer, before its feedback became available. This public benchmark was used earlier; these are online-stream results, not claims of unseen-benchmark generalization. The 80% target was not reached.':'每个分数均对应反馈可见之前的原始首答。本项目此前使用过该公开基准；这是在线序列成绩，不代表未见基准泛化。80% 目标未达到。',
    'One actual diagnosis per case, at most 72 snapshot calls. Later feedback can update future Harness versions, never old scores.':'每题仅执行一次实际诊断，最多调用 72 次快照工具。后续反馈仅能更新未来 Harness 版本，不能修改旧分数。',
    'ONLINE EVOLUTION / IMMUTABLE FIRST ANSWERS':'在线演进 / 不可覆盖的首答',
    'Experience, one incident at a time.':'每个案例，积累一份经验。',
    'A chronological record of first predictions and future-only Harness updates':'按时间记录首答及仅作用于后续案例的 Harness 更新',
    'Stream position':'序列位置', 'First-answer accuracy':'首答准确率',
    'Executable rules':'可执行规则', 'Original outcome':'原始诊断结果',
    'Accuracy and executable experience':'准确率与可执行经验', 'Rule count':'规则数量',
    'Lock first answer':'锁定首答', 'Release feedback & propose':'释放反馈并提议规则',
    'Inspect diagnosis and update':'查看诊断与更新', 'Adjacent events':'相邻事件',
    'ORIGINAL SCORES':'原始分数', 'Position':'位置', 'Incident':'案例',
    'First answer':'首答', 'Update':'更新', 'Admitted':'已准入',
    'Rejected':'已拒绝', 'No update':'无需更新', 'Advisor unavailable':'顾问不可用',
    'Unhealthy diagnosis':'诊断异常', 'accepted':'已准入', 'rejected':'已拒绝',
    'no_update':'无需更新', 'advisor_unavailable':'顾问不可用',
    'unhealthy_diagnosis':'诊断异常',
    'Reset evolution playback':'重置演进播放', 'Play evolution':'播放演进',
    'Pause evolution':'暂停演进', 'Next evolution event':'下一个演进事件',
    'Evolution stream position':'演进序列位置',
    'Recorded accuracy, Harness version and rule count over the stream':'序列中的准确率、Harness 版本和规则数记录',
    'FINAL HARNESS / EXECUTABLE EXPERIENCE':'最终 HARNESS / 可执行经验',
    'The evidence atlas.':'证据与经验图谱。',
    'Source-bound rules checked against past cached evidence; not a guarantee of future prediction stability.':'规则绑定证据来源，并在历史缓存证据上验证；不保证未来预测始终稳定。',
    'Final executable rules':'最终可执行规则', 'Admitted updates':'准入更新',
    'Rejected proposals':'被拒提议', 'Historical diagnosis retakes':'历史诊断重测数',
    'Experience topology':'经验拓扑', 'FINAL RULE BANK':'最终规则库',
    'Workload':'工作负载', 'Node':'节点', 'Namespace':'命名空间',
    'Executable predicates':'可执行谓词', 'All rules':'全部规则',
    'Rule':'规则', 'Cause':'原因', 'Scope':'范围', 'Origin':'来源',
    'Admitted evidence':'已准入证据', 'Inherited rule':'继承规则',
    'Inherited experience':'继承经验', 'Historical admission':'历史准入',
    'EXECUTABLE PREDICATE':'可执行谓词', 'Target':'目标', 'Rule filter':'规则筛选',
    'Final executable experience graph':'最终可执行经验图谱',
    'FINAL PREDICTIONS / PRESERVED TRAJECTORIES':'最终首答 / 保留的诊断轨迹',
    'Incident observatory.':'逐题诊断观测台。',
    'Exact diagnosis outcomes and recorded snapshot acquisition traces.':'精确诊断结果及已记录的快照证据采集轨迹。',
    'Case ID':'案例编号', 'Search case':'检索案例', 'Case filter':'案例筛选',
    'All first answers':'全部首答', 'First incorrect':'首答错误', 'Online stream':'在线序列', 'online stream':'在线序列',
    'All cases':'全部案例', 'Primary incorrect':'主要方法错误', 'Repaired cases':'修复案例',
    'Select a case':'选择案例', 'Evidence acquisition':'证据采集', 'Trace method':'轨迹方法',
    'Online JEV + PUCT':'在线 JEV + PUCT', 'Evolving JEV + PUCT':'演进 JEV + PUCT', 'Evolved Harness':'演进 Harness',
    'Reference Harness':'参考 Harness', 'Static tree':'静态树搜索', 'Plain JEV':'纯 JEV',
    'RECORDED TRAJECTORY':'已记录轨迹', 'Reset recorded trace':'重置轨迹播放',
    'Play recorded trace':'播放已记录轨迹', 'Pause recorded trace':'暂停轨迹播放',
    'Next recorded acquisition':'下一个采集步骤',
    'Recorded evidence acquisition path':'已记录的证据采集路径',
    'Unscored':'未评分', 'No matching cases':'没有匹配的案例',
    'Loading recorded trace':'正在加载已记录轨迹', 'Trace unavailable':'轨迹暂不可用',
    'No recorded trace':'没有已记录轨迹', 'Post-case update':'题后更新',
    'Action':'动作', 'Visits':'访问次数', 'Prior':'先验', 'Mean utility':'平均效用',
    'Recorded diagnostic evidence':'已记录的诊断证据', 'NOT NEW INFERENCE':'不是新推理',
    'Query':'原始问题', 'Evidence constraint':'证据约束', 'Integrity':'完整性',
    'Supported object–cause witnesses constrain the candidate bank.':'有支撑的对象—原因见证约束候选集合。',
    'No complete witness constraint was applied; ranked candidates determine the decision.':'没有应用完整的见证约束；诊断由候选排序决定。',
    'Recorded object scores · after alert adjustment':'已记录的对象分数 · 告警调整后',
    'Final candidate bank and scores':'最终候选集合与分数',
    'Post-case Harness update':'题后 Harness 更新',
    'Advisor proposal as recorded':'已记录的顾问提议',
    'Newly admitted executable rules':'新准入的可执行规则',
    'Admission checks for accepted predicates':'已准入谓词的检查结果',
    'History experience update':'历史经验更新', 'H / rules':'H / 规则',
    'Recorded first-answer trace; excerpts may be truncated; addresses and host paths redacted.':'已记录的首答轨迹；长输出可能被截为摘录；地址与主机路径已脱敏。',
    'METHOD / INFORMATION BARRIERS':'方法 / 信息隔离',
    'Small decisions. Evolving experience.':'小模型决策，经验持续演进。',
    'Frozen JEV weights · executable transfer · evidence-constrained search':'冻结 JEV 权重 · 可执行经验迁移 · 证据约束搜索',
    'Workflow PNG':'流程图 PNG', 'Interactive method':'动态方法页', 'EXECUTABLE EXPERIENCE, NOT WEIGHT UPDATES':'演进可执行经验，而非模型权重',
    'Evidence constrains decisions. Experience improves the constraints.':'证据约束决策，经验完善约束。',
    'A DeepSeek plugin-design RCA adapter separates evidence, frozen JEV ranking, bounded PUCT, immutable answers, post-case advice and admission. Case t uses Harness H_t; only after its first answer is locked does Qwen3.5 propose an update for subsequent cases. This adaptation is not the stock dsh Agent runtime.':'借鉴 DeepSeek 插件设计的 RCA 适配器，将证据、冻结 JEV 排序、有界 PUCT、不可覆盖首答、题后顾问和准入分离。第 t 题使用 Harness H_t；锁定首答后，Qwen3.5 才为后续案例提议更新。本适配器不是原版 dsh Agent 运行时。',
    'Grounded diagnosis':'证据驱动诊断',
    'Bind observations to their actual objects. Rank competing causes, acquire evidence and reject unsupported explanations.':'将观测绑定到实际对象，排序竞争根因、采集证据并排除缺乏支撑的解释。',
    'Verified evolution':'经验证的演进',
    'Admit source-bound predicates only with past-case support and precision checks. Matching cached evidence never re-runs a past diagnosis.':'仅准入有历史案例支撑、通过精度检查的来源绑定谓词。匹配缓存证据不重新执行历史诊断。',
    'First-answer verification':'首答验证',
    'Freeze JEV and runtime code. Each case runs once; its first answer and score cannot be replaced after feedback.':'冻结 JEV 与运行代码，每题只执行一次；反馈之后不得替换首答或分数。',
    'Method plane':'方法层', 'Diagnosis':'诊断', 'Verification':'验证',
    'Reset module layout':'重置模块布局', 'Diagnosis plane':'诊断层',
    'NO EVALUATION LABELS':'无评测答案输入', 'Public observations':'公开观测',
    'Query, logs, events and snapshot tools':'问题、日志、事件与快照工具',
    'Source-bound witnesses':'来源绑定的见证', 'Executable Harness':'可执行 Harness',
    'Ownership binding and contradiction filters':'归属绑定与矛盾过滤',
    'Object-consistent evidence':'对象一致的证据', 'JEV + bounded PUCT':'JEV + 有界 PUCT',
    '96 surrogate simulations · replan after evidence':'96 次代理模拟 · 获取证据后重新规划',
    '72-call cap · frozen weights':'72 次调用上限 · 冻结权重',
    'Immutable first answer':'不可覆盖的首答', 'Persisted diagnosis':'落盘诊断',
    'Historical feedback':'历史反馈', 'JEV + bounded search':'JEV + 有界搜索',
    'Persist before releasing case feedback':'释放本题反馈之前落盘',
    'Trace and provenance hashes':'轨迹与来源哈希',
    'After each immutable first answer':'每个不可覆盖首答之后',
    'Reusable predicates, not neural weight updates':'可复用谓词，不更新神经权重',
    'Experience evolution':'经验演进', 'POST-CASE FEEDBACK':'题后反馈',
    'Completed-case feedback':'已完成案例的反馈',
    'Completed trace and confirmed diagnosis':'完整轨迹与确认的诊断',
    'Preserve historical memory':'保留历史记忆', 'Qwen3.5-27B advisor':'Qwen3.5-27B 顾问',
    'One reusable, atomic evidence predicate':'一个可复用的原子证据谓词',
    'No case-ID or answer lookup':'不按案例编号查找答案',
    'Verification + admission':'验证与准入',
    'Past-only predicate precision and ownership checks':'仅用历史证据检查谓词精度与归属',
    'No conflicting proof on past correct cases':'历史正确案例中无冲突见证',
    'Harness for the next case':'用于下一题的 Harness',
    'Accept, reject or already covered':'接受、拒绝或已覆盖',
    'Single-pass verification':'单遍验证', 'LABEL ACCESS BARRIER':'答案访问隔离',
    'Diagnose once':'诊断一次', 'Next case only':'仅用于后续题',
    'EXACT DIAGNOSIS':'精确诊断', 'Correct =':'正确 =', 'object match':'对象匹配',
    'cause match':'原因匹配', 'JEV priors + PUCT acquisition + executable evidence':'JEV 先验 + PUCT 采集 + 可执行证据',
    'Interpretation boundary':'结论边界',
    '754 chronological first answers. Only completed feedback can affect the next case. The public benchmark was used earlier by this project; past predicate validation does not guarantee future accuracy.':'754 个按时间顺序记录的首答。仅已完成案例的反馈可影响后续题。本项目此前使用过该公开基准；历史谓词验证不保证未来准确率。',
    'One evolving method · 72 actual calls per case':'单一演进方法 · 每题最多 72 次实际调用',
    'Frozen JEV ranks candidates and evidence checks. PUCT plans bounded acquisitions using surrogate utility, not actual future observations. Current-case feedback is not available.':'冻结 JEV 排序候选与证据检查。PUCT 使用代理效用规划有界采集，不读取实际未来观测。当前题反馈不可见。',
    'After the first answer is locked, the LLM proposes a reusable evidence predicate. Admission checks cached past evidence only; accepted changes apply to the next case, never a replacement answer.':'首答锁定后，LLM 提议可复用证据谓词。准入仅检查历史缓存证据；接受的更新只作用于后续题，不替换旧答案。',
    '754 unique first answers are permanently scored. Runtime code and JEV stay frozen while Harness versions evolve. No old diagnosis is re-run after feedback.':'永久保留 754 个唯一首答的分数。Harness 演进期间运行代码和 JEV 保持冻结。收到反馈后不重跑旧诊断。',
    'BENCHMARK / REPRODUCIBLE CLOUD INCIDENTS':'基准 / 可复现的云故障',
    'Agentic root cause analysis in Kubernetes microservice systems':'Kubernetes 微服务系统中的智能体根因分析',
    'Benchmark source':'基准来源', 'TASK & EVIDENCE':'任务与证据',
    'Find the fault object and its cause from operational evidence.':'从运维证据中定位故障对象及根因。',
    'Cloud-OpsBench represents cloud incidents as immutable state snapshots and cached diagnostic tools. Queries, logs, Kubernetes events and state, metrics and available source code support deterministic replay without deploying a live cluster.':'Cloud-OpsBench 将云故障组织为不可变状态快照及缓存诊断工具。问题、日志、Kubernetes 事件与状态、指标和可用源码支持确定性回放，无需部署实时集群。',
    'Unique fault cases':'唯一故障案例', 'Fault types':'故障类型',
    'Microservice systems':'微服务系统', 'System composition':'系统组成',
    '754 INCIDENTS':'754 个案例', 'Evidence and label boundary':'证据与答案边界',
    'Raw benchmark assets and model weights are external dependencies, not bundled with EvoJev.':'原始基准与模型权重是外部依赖，不随 EvoJev 打包。',
    'Solver input':'诊断器输入', 'Query, namespace and public observations':'问题、命名空间与公开观测',
    'Post-case feedback':'题后反馈',
    'Only after the same case’s immutable first answer':'仅在本题不可覆盖首答之后',
    'Future cases':'后续案例', 'Labels inaccessible to the solver and advisor':'诊断器与顾问均不可读取答案',
    'Fault families':'故障类别', '8 CATEGORIES':'8 个类别', 'Admission':'准入',
    'Scheduling':'调度', 'Startup':'启动', 'Runtime':'运行', 'Service routing':'服务路由',
    'Performance':'性能', 'Infrastructure':'基础设施', 'Code defects':'代码缺陷',
    'This study’s protocol':'本研究协议', 'EXACT OBJECT + CAUSE':'对象与原因联合正确',
    'Partition':'分区', 'Role':'作用', 'Growing':'持续增长',
    'One first answer per case; feedback released afterward':'每题一个首答；之后释放反馈',
    'Past evidence memory':'历史证据记忆',
    'Predicate checks only; no past-case re-inference':'仅检查谓词，不重推理历史案例',
    'Report exact object-and-cause prequential accuracy from immutable first predictions. Future labels are unavailable to the solver and advisor; completed-case feedback is available after the original answer. Prior public-benchmark use remains disclosed.':'基于不可覆盖的首次预测统计对象与原因联合正确的在线准确率。诊断器和顾问不能获取未来题答案；已完成题反馈在首答之后可见。仍明确披露此前使用公开基准的事实。',
    'One evolving method; 72 actual tool calls per case.':'单一演进方法；每题最多 72 次实际工具调用。',
    'CITE THE BENCHMARK':'引用基准', 'Official repository':'官方代码仓库',
    'EvoJev / Cloud-OpsBench · verified final research artifacts':'EvoJev / Cloud-OpsBench · 已验证的最终研究成果'
  };
  const patterns = [
    [/^(\d+) \/ (\d+) cases$/, '$1 / $2 个案例'],
    [/^(\d+) CASES$/, '$1 个案例'], [/^(\d+) RULES$/, '$1 条规则'],
    [/^(\d+) committed events$/, '$1 个已提交事件'],
    [/^(\d+) unique cases · (\d+) original predictions$/, '$1 个唯一案例 · $2 个原始预测'],
    [/^(\d+) rule admission steps$/, '$1 次规则准入'],
    [/^(\d+) admitted updates$/, '$1 次准入更新'],
    [/^(\d+) correct \/ (\d+) diagnosed$/, '$1 题正确 / $2 题已诊断'],
    [/^H(\d+) used for this diagnosis$/, '本次诊断使用 H$1'],
    [/^(\d+) admission steps$/, '$1 次准入'],
    [/^H(\d+) → H(\d+) · (\d+) new rules$/, 'H$1 → H$2 · $3 条新规则'],
    [/^Diagnose with H(\d+)$/, '使用 H$1 诊断'],
    [/^H(\d+) for subsequent cases$/, 'H$1 用于后续案例'],
    [/^EVENT (\d+) \/ (case_\d+)$/, '事件 $1 / $2'],
    [/^Stream (\d+) · Harness (\d+)$/, '序列 $1 · Harness $2'],
    [/^Stream (\d+), (case_\d+)$/, '序列 $1，$2'],
    [/^Next Harness version: (\d+)$/, '下一个 Harness 版本：$1'],
    [/^(\d+) new rules · original score unchanged$/, '$1 条新规则 · 原始分数不变'],
    [/^(\d+) calls · ([\d.]+) sec$/, '$1 次调用 · $2 秒'],
    [/^RECORDED (\d+) \/ (\d+)$/, '已记录 $1 / $2'],
    [/^Recorded output · (\d+) characters( · excerpt)?$/, (_, n, excerpt) => `已记录输出 · ${n} 字符${excerpt?' · 摘录':''}`],
    [/^Recorded PUCT · (\d+) simulations · (\d+)-call horizon$/, '已记录 PUCT · $1 次模拟 · $2 次调用视野'],
    [/^Action indices · (\d+) \/ (\d+) recorded root children, ordered by visits$/, '动作编号 · $1 / $2 个已记录根节点子分支，按访问次数排序'],
    [/^First answer saved before feedback · (\d+) new inference calls during export$/, '反馈之前保存首答 · 导出期间 $1 次新推理调用'],
    [/^H(\d+) → H(\d+) · (\d+) → (\d+) rules · later cases only$/, 'H$1 → H$2 · $3 → $4 条规则 · 仅作用于后续题'],
    [/^(\d+) final rules · (\d+) admitted in this revision$/, '$1 条最终规则 · 本轮准入 $2 次'],
    [/^(\d+) predicates$/, '$1 个谓词'],
    [/^Move (.+)$/, (_, name) => `移动 ${chinese[name]||name}`],
    [/^(case_\d+) · (\d+) cases$/, '$1 · $2 个案例'],
    [/^(\d+) · (case_\d+) · (correct|incorrect) · (Admitted|Rejected|No update|Advisor unavailable|Unhealthy diagnosis)$/, (_, n, id, result, update) => `${n} · ${id} · ${chinese[result]} · ${chinese[update]}`]
  ];
  let language='en', theme='light';
  function translate(value, locale=language) {
    if(locale!=='zh')return value;
    const key=value.trim();
    let result=chinese[key];
    if(result===undefined)for(const [pattern,replacement] of patterns){if(pattern.test(key)){result=key.replace(pattern,replacement);break;}}
    return result===undefined?value:value.replace(key,result);
  }
  globalThis.EvoJevPreferences={t:translate};
  if(typeof document==='undefined')return;
  const root=document.documentElement, themeButton=document.getElementById('theme-toggle'), languageButton=document.getElementById('language-toggle');
  const records=new WeakMap(), attributeRecords=new WeakMap();
  const excluded='pre,code,script,style,svg,.task-strip b,.benchmark-citation p,.witness h3,.step b,#theme-toggle,#language-toggle';
  const attributes=['title','aria-label','placeholder'];
  try{theme=localStorage.getItem('evojev-theme')==='dark'?'dark':'light';language=localStorage.getItem('evojev-language')==='zh'?'zh':'en';}catch{}
  function replaceText(node) {
    if(!node.parentElement||node.parentElement.closest(excluded))return;
    const previous=records.get(node), source=previous&&node.nodeValue===previous.rendered?previous.source:node.nodeValue;
    const rendered=translate(source);
    records.set(node,{source,rendered});
    if(node.nodeValue!==rendered)node.nodeValue=rendered;
  }
  function replaceAttributes(element) {
    if(element.closest(excluded))return;
    const record=attributeRecords.get(element)||{};
    for(const name of attributes){
      const value=element.getAttribute(name);if(value===null)continue;
      const previous=record[name],source=previous&&value===previous.rendered?previous.source:value,rendered=translate(source);
      record[name]={source,rendered};if(value!==rendered)element.setAttribute(name,rendered);
    }
    attributeRecords.set(element,record);
  }
  function visit(node) {
    if(node.nodeType===3){replaceText(node);return;}
    if(node.nodeType!==1||node.matches(excluded))return;
    replaceAttributes(node);
    for(const child of node.childNodes)visit(child);
  }
  const dirty=new Set();let scheduled=false;
  function collect(mutations){
    for(const m of mutations){
      if(m.type==='childList')for(const node of m.addedNodes)dirty.add(node);
      else dirty.add(m.target);
    }
  }
  const observer=new MutationObserver(mutations=>{
    collect(mutations);
    if(!scheduled&&dirty.size){scheduled=true;queueMicrotask(flush);}
  });
  function observe(){observer.observe(document.body,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:attributes});}
  function flush(){
    scheduled=false;collect(observer.takeRecords());observer.disconnect();
    for(const node of dirty)if(node.isConnected)visit(node);
    dirty.clear();observe();
  }
  function controls(){
    themeButton.setAttribute('aria-checked',String(theme==='dark'));
    themeButton.setAttribute('aria-label',language==='zh'?'深色模式':'Dark appearance');
    themeButton.title=language==='zh'?(theme==='dark'?'切换为亮色':'切换为深色'):(theme==='dark'?'Switch to light theme':'Switch to dark theme');
    themeButton.innerHTML=`<i data-lucide="${theme==='dark'?'sun':'moon'}"></i>`;
    const label=language==='zh'?'Switch to English':'切换为中文';
    languageButton.title=label;languageButton.setAttribute('aria-label',label);
    languageButton.innerHTML=`<i data-lucide="languages"></i><span>${language==='zh'?'中':'EN'}</span>`;
    globalThis.lucide?.createIcons();
  }
  function apply(){
    observer.disconnect();root.dataset.theme=theme;root.lang=language==='zh'?'zh-CN':'en';
    document.querySelector('meta[name=theme-color]').content=theme==='dark'?'#111618':'#ffffff';
    visit(document.body);controls();dirty.clear();observe();
    window.dispatchEvent(new Event('evojev-preferences'));
  }
  themeButton.addEventListener('click',()=>{theme=theme==='dark'?'light':'dark';try{localStorage.setItem('evojev-theme',theme);}catch{}apply();});
  languageButton.addEventListener('click',()=>{language=language==='zh'?'en':'zh';try{localStorage.setItem('evojev-language',language);}catch{}apply();});
  window.addEventListener('evojev-preferences',()=>{
    if(typeof background==='function')background(performance.now());
    if(document.getElementById('evolution')?.classList.contains('active')&&typeof drawEvolution==='function')drawEvolution();
    if(document.getElementById('knowledge')?.classList.contains('active')&&typeof drawMap==='function')drawMap();
  });
  apply();
})();
