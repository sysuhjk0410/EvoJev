'use strict';
let evolutionIndex=753,evolutionPlaying=false,evolutionClock=0;
const decisionLabel=v=>({accepted:'Admitted',rejected:'Rejected',no_update:'No update',advisor_unavailable:'Advisor unavailable',unhealthy_diagnosis:'Unhealthy diagnosis'}[v]||v);
const evolutionView=document.createElement('section');
evolutionView.id='evolution';evolutionView.className='view';
evolutionView.innerHTML=`<div class="section-heading"><div><div class="eyebrow">ONLINE EVOLUTION / IMMUTABLE FIRST ANSWERS</div><h1>Experience, one incident at a time.</h1><p class="muted">A chronological record of first predictions and future-only Harness updates</p></div><span class="badge">754 committed events</span></div><div class="data-surface evolution-surface"><div class="evolution-controls"><div><button id="evolution-reset" class="icon" title="Reset evolution playback" aria-label="Reset evolution playback"><i data-lucide="rotate-ccw"></i></button><button id="evolution-play" class="icon" title="Play evolution" aria-label="Play evolution"><i data-lucide="play"></i></button><button id="evolution-next" class="icon" title="Next evolution event" aria-label="Next evolution event"><i data-lucide="step-forward"></i></button></div><label for="evolution-slider">Stream position <strong id="evolution-position">754 / 754</strong></label><input id="evolution-slider" type="range" min="0" max="753" value="753" aria-label="Evolution stream position"></div><div class="evolution-metrics" id="evolution-metrics"></div><div class="block-heading"><h2>Accuracy and executable experience</h2><div class="legend"><span><i style="background:#167d73"></i>First-answer accuracy</span><span><i style="background:#426fcc"></i>Harness version</span><span><i style="background:#b95f4c"></i>Rule count</span></div></div><canvas id="evolution-chart" aria-label="Recorded accuracy, Harness version and rule count over the stream"></canvas><div class="event-raster" id="event-raster"></div><div class="evolution-detail" id="evolution-detail"></div><div class="event-ledger" id="event-ledger"></div></div>`;
$('knowledge').before(evolutionView);
const evolutionNav=document.createElement('button');evolutionNav.className='nav';evolutionNav.dataset.view='evolution';evolutionNav.title='Harness evolution';evolutionNav.innerHTML='<i data-lucide="git-branch"></i><span>Evolution</span><small>02</small>';
document.querySelector('[data-view=knowledge]').before(evolutionNav);
document.querySelectorAll('.nav').forEach((el,i)=>{el.querySelector('small').textContent=String(i+1).padStart(2,'0');});
evolutionNav.addEventListener('click',()=>{view('evolution');evolutionPlaying=false;renderEvolution();});
const outputBlock=(title,value)=>`<details class="record-block"><summary>${esc(title)}</summary><pre>${esc(typeof value==='string'?value:JSON.stringify(value,null,2))}</pre></details>`;
function renderEvolution(){
  if(!isOnline())return;
  evolutionIndex=Math.min(data.cases.length-1,Math.max(0,evolutionIndex));
  const rows=data.cases.slice(0,evolutionIndex+1),c=rows.at(-1),correct=rows.filter(r=>r.arms[primary].correct).length;
  const admitted=rows.filter(r=>r.update.decision==='accepted').length,ruleCount=data.timeline.slice(0,evolutionIndex+1).reduce((n,e)=>n+(e.new_rule_hashes?.length||0),0);
  $('evolution-slider').value=evolutionIndex;$('evolution-position').textContent=`${evolutionIndex+1} / ${data.cases.length}`;
  $('evolution-metrics').innerHTML=`<div><span>First-answer accuracy</span><strong>${pct(correct,rows.length)}</strong><small>${correct} correct / ${rows.length} diagnosed</small></div><div><span>Harness</span><strong>H${c.update.version_after}</strong><small>H${c.harness_version} used for this diagnosis</small></div><div><span>Executable rules</span><strong>${ruleCount}</strong><small>${admitted} admission steps</small></div><div><span>Original outcome</span><strong class="${c.arms[primary].correct?'good':'bad'}">${c.arms[primary].correct?'Correct':'Incorrect'}</strong><small>${c.case}</small></div>`;
  $('evolution-detail').innerHTML=`<div><div class="eyebrow">EVENT ${evolutionIndex+1} / ${esc(c.case)}</div><h2>${esc(decisionLabel(c.update.decision))}</h2><p>H${c.harness_version} → H${c.update.version_after} · ${c.update.new_rules} new rules</p></div><ol class="event-flow"><li><i data-lucide="scan-search"></i><span>Diagnose with H${c.harness_version}</span></li><li><i data-lucide="lock"></i><span>Lock first answer</span></li><li><i data-lucide="brain-circuit"></i><span>Release feedback &amp; propose</span></li><li><i data-lucide="shield-check"></i><span>${esc(decisionLabel(c.update.decision))}</span></li><li><i data-lucide="arrow-right"></i><span>H${c.update.version_after} for subsequent cases</span></li></ol><button class="command" id="open-evolution-case"><i data-lucide="arrow-up-right"></i>Inspect diagnosis and update</button>`;
  $('open-evolution-case').onclick=()=>{view('cases');selectCase(c.case);};
  $('event-ledger').innerHTML=`<div class="block-heading"><h2>Adjacent events</h2><span class="mono">ORIGINAL SCORES</span></div><div class="table-scroll"><table><thead><tr><th>Position</th><th>Incident</th><th>First answer</th><th>Update</th><th>Harness</th></tr></thead><tbody>${data.cases.slice(Math.max(0,evolutionIndex-4),Math.min(data.cases.length,evolutionIndex+5)).map(c=>`<tr class="${c.stream_index===evolutionIndex?'selected':''}"><td>${c.stream_index+1}</td><td><button class="text-link" data-event="${c.stream_index}">${esc(c.case)}</button></td><td class="${c.arms[primary].correct?'good':'bad'}">${c.arms[primary].correct?'Correct':'Incorrect'}</td><td>${esc(decisionLabel(c.update.decision))}</td><td>H${c.harness_version} → H${c.update.version_after}</td></tr>`).join('')}</tbody></table></div>`;
  $('event-ledger').querySelectorAll('[data-event]').forEach(b=>b.onclick=()=>{evolutionIndex=Number(b.dataset.event);renderEvolution();});
  $('event-raster').querySelectorAll('[data-event]').forEach(b=>b.classList.toggle('selected',Number(b.dataset.event)===evolutionIndex));
  $('evolution-play').innerHTML=`<i data-lucide="${evolutionPlaying?'pause':'play'}"></i>`;
  $('evolution-play').setAttribute('aria-label',evolutionPlaying?'Pause evolution':'Play evolution');
  drawEvolution();icons();
}
function drawEvolution(){
  if(!isOnline())return;
  const{x,w,h}=canvas('evolution-chart');if(!w)return;
  const p={l:48,r:48,t:28,b:30},bw=w-p.l-p.r,bh=h-p.t-p.b,total=data.cases.length;
  x.font='12px ui-monospace,monospace';x.lineWidth=1;
  for(let j=0;j<=4;j++){const y=p.t+bh*j/4;x.strokeStyle='#dee8e8';x.beginPath();x.moveTo(p.l,y);x.lineTo(w-p.r,y);x.stroke();x.fillStyle='#167d73';x.fillText(`${100-j*25}%`,1,y+4);x.fillStyle='#426fcc';x.fillText(String(160-j*40),w-39,y+4);}
  x.fillStyle='#426fcc';x.fillText(window.EvoJevPreferences?.t('H / rules')||'H / rules',w-92,13);
  let correct=0,rules=0;const accuracy=[],versions=[],ruleValues=[];
  data.cases.forEach((c,i)=>{correct+=Number(c.arms[primary].correct);rules+=data.timeline[i].new_rule_hashes?.length||0;accuracy.push(correct/(i+1));versions.push(c.update.version_after/160);ruleValues.push(rules/160);});
  for(const [values,color] of [[accuracy,'#167d73'],[versions,'#426fcc'],[ruleValues,'#b95f4c']]){x.strokeStyle=color;x.lineWidth=2.3;x.beginPath();values.forEach((v,i)=>{const xx=p.l+bw*(i+1)/total,yy=p.t+bh*(1-v);i?x.lineTo(xx,yy):x.moveTo(xx,yy);});x.stroke();}
  const xx=p.l+bw*(evolutionIndex+1)/total;x.fillStyle='#426fcc09';x.fillRect(p.l,p.t,xx-p.l,bh);x.strokeStyle='#203237';x.setLineDash([4,4]);x.beginPath();x.moveTo(xx,p.t);x.lineTo(xx,p.t+bh);x.stroke();x.setLineDash([]);
  for(const [values,color] of [[accuracy,'#167d73'],[versions,'#426fcc'],[ruleValues,'#b95f4c']]){x.fillStyle=color;x.beginPath();x.arc(xx,p.t+bh*(1-values[evolutionIndex]),4,0,Math.PI*2);x.fill();}
  x.fillStyle='#596d74';[1,188,377,565,754].forEach(i=>x.fillText(String(i),p.l+bw*i/total-10,h-7));
}
const oldOverview=overview;
overview=function(){oldOverview();if(!isOnline())return;
  const s=data.summary.metrics[primary],wrong=s.total-s.correct;
  $('bars').innerHTML=`<div class="outcome-ring" style="--success:${100*s.correct/s.total}%"><div><strong>${pct(s.correct,s.total)}</strong><span>Exact object + cause</span></div></div><div class="outcome-key"><span><i></i>Correct <b>${s.correct}</b></span><span><i></i>Incorrect <b>${wrong}</b></span></div><div class="audit-line"><i data-lucide="shield-check"></i><span>754 unique starts · no retakes · audit passed</span></div>`;
  $('threshold-note').textContent+=' The 80% target was not reached.';
  $('event-raster').innerHTML=data.cases.map(c=>`<button class="raster-event ${c.arms[primary].correct?'correct':'incorrect'} ${c.update.decision==='accepted'?'admission':''}" data-event="${c.stream_index}" title="${c.stream_index+1} · ${c.case} · ${c.arms[primary].correct?'correct':'incorrect'} · ${decisionLabel(c.update.decision)}" aria-label="Stream ${c.stream_index+1}, ${c.case}"></button>`).join('');
  $('event-raster').querySelectorAll('[data-event]').forEach(b=>b.onclick=()=>{evolutionPlaying=false;evolutionIndex=Number(b.dataset.event);renderEvolution();});
  renderEvolution();icons();
};
const originalTraceView=traceView;
traceView=function(){originalTraceView();const t=traces?.[$('arm-select').value],d=t?.diagnostic;if(!d)return;
  document.querySelectorAll('#trace-steps .step').forEach((el,i)=>{
    const observation=d.observations[i]?.excerpt;
    if(!observation)return;
    el.querySelector('div').insertAdjacentHTML('beforeend',outputBlock(`Recorded output · ${observation.original_characters} characters${observation.truncated?' · excerpt':''}`,observation.text));
  });
  let panel=$('diagnostic-details');if(!panel){panel=document.createElement('div');panel.id='diagnostic-details';$('trace-steps').after(panel);}
  panel.innerHTML=`<div class="block-heading"><h2>Recorded diagnostic evidence</h2><span class="mono">NOT NEW INFERENCE</span></div><div class="task-strip"><span>Query</span><b>${esc(d.task.query)}</b><span>Namespace</span><b>${esc(d.task.namespace)}</b></div><div class="diagnostic-summary"><div><h3>Evidence constraint</h3><p>${d.constraint_applied?'Supported object–cause witnesses constrain the candidate bank.':'No complete witness constraint was applied; ranked candidates determine the decision.'}</p></div><div><h3>Integrity</h3><p>First answer saved before feedback · ${d.integrity.new_inference_calls} new inference calls during export</p></div></div>${outputBlock('Recorded object scores · after alert adjustment',d.object_scores)}${outputBlock('Final candidate bank and scores',d.candidates)}${d.supported_pairs.map(p=>`<div class="witness"><h3>${esc(p.fault_object)} · ${esc(p.root_cause)}</h3><span class="mono">${esc(p.rule)}</span>${p.witnesses.map(w=>outputBlock(`${w.id} · ${w.tool} · ${w.object}`,w.excerpt.text)).join('')}</div>`).join('')}<div class="block-heading update-heading"><h2>Post-case Harness update</h2><span class="tag ${d.update.decision==='accepted'?'accepted':''}">${esc(decisionLabel(d.update.decision))}</span></div><p class="caption">H${d.update.version_before} → H${d.update.version_after} · ${d.update.rules_before} → ${d.update.rules_after} rules · later cases only</p>${outputBlock('Advisor proposal as recorded',d.update.proposal)}${outputBlock('Newly admitted executable rules',d.update.new_rules)}${outputBlock('Admission checks for accepted predicates',d.update.admitted_checks)}${outputBlock('History experience update',d.update.experience)}<p class="caption">${esc(d.display_scope)}</p>`;
};
$('evolution-slider').addEventListener('input',()=>{evolutionPlaying=false;evolutionIndex=Number($('evolution-slider').value);renderEvolution();});
$('evolution-reset').onclick=()=>{evolutionPlaying=false;evolutionIndex=0;renderEvolution();};
$('evolution-next').onclick=()=>{evolutionPlaying=false;evolutionIndex++;renderEvolution();};
$('evolution-play').onclick=()=>{if(evolutionIndex>=753)evolutionIndex=0;evolutionPlaying=!evolutionPlaying;evolutionClock=performance.now();renderEvolution();};
function evolutionFrame(time){if(evolutionPlaying&&!document.hidden&&time-evolutionClock>350){evolutionClock=time;evolutionIndex++;if(evolutionIndex>=753)evolutionPlaying=false;renderEvolution();}requestAnimationFrame(evolutionFrame);}
requestAnimationFrame(evolutionFrame);
window.addEventListener('resize',()=>{if($('evolution').classList.contains('active'))drawEvolution();});
icons();
