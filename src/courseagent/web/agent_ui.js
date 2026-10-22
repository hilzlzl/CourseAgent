/* Autonomous tasks do not overwrite the optional teacher workbench. */
(()=>{
 let timer=null,eventStream=null,currentTaskId=null,refreshSequence=0;
 async function getTask(path){
  const r=await fetch(path,{method:'GET',cache:'no-store',signal:AbortSignal.timeout(15000)});
  if(!r.ok)throw Error('任务进度读取失败（'+r.status+'），请刷新进度');
  return r.json();
 }
 async function submitTask(payload){
  const r=await fetch('/api/agent-start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload),signal:AbortSignal.timeout(15000)});
  const data=await r.json();if(!r.ok)throw Error(data.error||'提交未完成');return data;
 }
 function showAgentError(e){
  const pending=$('agent-submitting');if(pending)pending.remove();
  let box=$('agent-error');if(!box){box=document.createElement('p');box.id='agent-error';box.className='warning';$('agent-tasks').prepend(box);}
  box.textContent=e.name==='TimeoutError'?'请求超时，后台可能已接收任务。请查看任务列表，不要重复提交。':e.message||'请求未完成，请刷新进度';status(box.textContent,true);
 }

 // Both entry points edit the same requirement.
 const syncPrompt=(from,to)=>{to.value=from.value;};
 $('agent-prompt').addEventListener('input',()=>syncPrompt($('agent-prompt'),$('prompt')));
 $('prompt').addEventListener('input',()=>syncPrompt($('prompt'),$('agent-prompt')));
 syncPrompt($('agent-prompt'),$('prompt'));
 const duration=n=>`${Math.floor((n||0)/60)}分${(n||0)%60}秒`;
 const elapsed=t=>duration(t.elapsed_seconds);

 const actions={adapt:'改编已有素材',search:'继续搜索',replace:'替换问题题',fix:'修复题目',repair_statements:'保留原题，修复编程题说明',retry_verification:'继续局部验证',retry_sources:'恢复普通题处理',retry_programming_sources:'自动恢复编程题来源',extend_sources:'自动继续补缺题型',deliver:'交付结果',stop:'停止并说明原因'};
 const labels={queued:'等待 Worker 接手',running:'自主执行中',importing:'正在导入与核对',completed:'已交付未发布试卷',ready:'本地生成完成',needs_attention:'已暂停，需要继续',interrupted:'任务中断',stopped:'已手动停止'};
 function selectionSummary(t){
  const s=t.selection_summary;if(!s)return '<p class="muted">正在解析题型数量，随后显示候选题进度。</p>';
  const names={'1':'单选','2':'多选','3':'判断','4':'填空','5':'简答/应用'};
  const parts=Object.entries(s.type_counts||{}).filter(([,v])=>v.requested).map(([k,v])=>({name:names[k]||k,...v}));
  if(s.programming_count?.requested)parts.push({name:'编程',...s.programming_count});
  if(!parts.length)return '';
  const actual=parts.reduce((n,v)=>n+v.selected,0),wanted=parts.reduce((n,v)=>n+v.requested,0);
  return `<div class="agent-progress"><div class="row"><strong>候选数量 ${actual} / ${wanted}</strong><span class="muted">${t.status==='completed'?'已导入头歌并回读核对':t.status==='importing'?'数量已匹配，正在头歌导入与核对':['needs_attention','interrupted'].includes(t.status)?'已暂停，候选题已保留':actual===wanted?'数量已匹配，仍需完成质量检查与交付':'正在补齐候选题'}</span></div><div class="agent-counts">${parts.map(v=>`<div><span>${esc(v.name)}</span><strong>${v.selected}<small> / ${v.requested}</small></strong><progress max="${v.requested}" value="${Math.min(v.selected,v.requested)}" aria-label="${esc(v.name)}候选题进度"></progress></div>`).join('')}</div><p class="muted">${t.status==='completed'?'本次试卷已保存到头歌，尚未发布。':t.status==='importing'?'本地组卷已完成，正在保存平台试卷与完整测试用例；完成后显示草稿入口。':'候选匹配数量会随搜题、改编和检查更新，不代表已通过最终校验或已上传。'}</p></div>`;
 }
 function verificationSummary(t){
  const v=t.verification_progress;if(!v?.total)return '';
  const stages={statement_adaptation:'整理完整程序题面并核对输入输出',material_alignment:'核对资料提取与题答匹配',source_discover:'获取来源题解代码',source_assessment:'分析评测要求',source_adapt:'适配来源程序',source_public_samples:'核对来源程序的公开样例',source_replace:'来源程序不适用，准备换题',source_design:'设计边界与隐藏输入',source_execute:'执行与计算隐藏输出',source_fallback:'升级加强验证',assess_specification:'规格审查',solve:'参考解法',independent:'独立解法',independent_code:'独立解法',independent_brute_code:'小规模朴素解法',independent_input_validator_code:'输入合法性检查',design_wrong_solutions:'错误对照',design_inputs:'测试输入',execute_checks:'执行核对',blind_solve:'独立作答',answer_compare:'答案核对'};
  const active=[...new Set((v.items||[]).filter(q=>q.status!=='verified').map(q=>stages[q.stage]).filter(Boolean))];
  const paused=['needs_attention','interrupted'].includes(t.status);
  const requestFailures=(v.items||[]).filter(q=>q.status!=='verified'&&['transport','output_limit','configuration','budget'].includes(q.failure_code)).length;
  const pendingNote=requestFailures?` · ${requestFailures} 道核验请求未完成，尚未判定题目对错`:'';
  return `<p class="muted">单题核验通过 ${v.verified} / ${v.total} 道${v.trusted_material_count?' · '+v.trusted_material_count+' 道采用资料标准答案':''}${pendingNote}${active.length?(paused?' · 未完成：':' · 当前：')+esc(active.join('、')):''}。整卷还需检查重复与题间冲突；已完成步骤会保留，重试只处理未完成部分。</p>`;
 }
 async function stopTask(identity){
  const r=await fetch('/api/agent-tasks/'+identity+'/stop',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}',signal:AbortSignal.timeout(15000)});
  const data=await r.json();if(!r.ok)throw Error(data.error||'停止失败');
  status('任务已停止，已有题目已保留。');await refresh();
 }
 function diversitySummary(t){
  const d=t.selection_diversity,c=t.teaching_coverage;
  if(!d?.selected_count)return '';
  const missed=(c?.goals||[]).filter(g=>g.suggested_count&&!g.matched_ids?.length);
  return `<p class="muted">近期选题参考：${d.history_task_count||0} 份已交付作业 · 本次复用 ${d.recent_reused_count||0} 道。${missed.length?'尚无覆盖线索：'+esc(missed.map(g=>g.name).join('、'))+'。':''}覆盖统计包含普通题和编程题，仅作教学参考。</p>`;
 }
 function replacementSummary(t){
  const items=t.replacement_history||[];
  if(!items.length)return '';
  return `<details><summary>换题记录（${items.length}）</summary>${items.map(r=>`<p>${esc(r.old_title)} → ${esc(r.new_title||'正在寻找替换题')}</p><p class="muted">原因：${esc(r.reason)}${r.new_id?'；'+(r.status==='passed_final_validation'?'已通过最终检查':r.status==='replaced_again'?'补入后又被替换，见后续记录':'已选入，等待最终检查'):''}</p>`).join('')}</details>`;
 }
 function taskNotice(t){
  if(t.status==='completed')return `<div class="agent-success" role="status" aria-label="作业完成"><span class="agent-success-icon" aria-hidden="true">✓</span><div><strong>作业已成功保存到头歌</strong><p>平台保存与回读核对已完成，试卷尚未发布。</p>${t.draft_url&&/^https:\/\/www\.educoder\.net\/classrooms\//.test(t.draft_url)?`<a target="_blank" rel="noopener" href="${esc(t.draft_url)}">查看头歌未发布试卷 →</a>`:''}</div></div>`;
  if(t.status==='ready')return '<div class="agent-success" role="status" aria-label="本地演示完成"><span class="agent-success-icon" aria-hidden="true">✓</span><div><strong>本地组卷已完成</strong><p>本次为本地演示，尚未上传头歌。</p></div></div>';
  if(!['needs_attention','interrupted'].includes(t.status))return '';
  const failures=new Set((t.verification_progress?.items||[]).map(q=>q.failure_code));
  let reason=t.message||'任务已停止执行，已有成果已保存。';
  if(!t.message&&failures.has('transport'))reason='模型接口连接中断或超时，自动重试后仍未恢复。已有题目已保存。';
  else if(!t.message&&failures.has('output_limit'))reason='模型输出被长度限制截断，自动重试后仍未恢复。已有题目已保存。';
  return `<div class="warning" role="status"><strong>任务已暂停${t.verification_progress?.total?'：验证通过 '+t.verification_progress.verified+' / '+t.verification_progress.total+' 道':''}</strong><p>${esc(reason)}</p><p>后台当前没有继续运行。${t.can_resume?'本轮自动恢复已结束。可继续当前任务，只补缺题或恢复失败步骤；已完成成果会保留。':'请查看下方检查记录和恢复入口。'}</p></div>`;
 }
 function taskCard(t){
  return `<div class="source-card" data-agent-task="${esc(t.id)}"><strong>${esc(labels[t.status]||t.status)}</strong><p>${esc(t.request)}</p>${taskNotice(t)}${selectionSummary(t)}${diversitySummary(t)}${replacementSummary(t)}${verificationSummary(t)}${t.branches?`<p class="muted">普通题：${esc(t.branches.ordinary||'准备中')}<br>编程题：${esc(t.branches.programming||'准备中')}</p>`:''}${t.status==='running'&&t.coding_search_progress?`<p class="muted">编程搜题：已读 ${t.coding_search_progress.pages} 页 · 已复核候选 ${t.coding_search_progress.candidate_count} 道 · 仍缺 ${t.coding_search_progress.missing} 道（随后执行验证）</p>`:''}${t.programming_verification_summary?`<p class="muted">编程评测：${t.programming_verification_summary.checked} / ${t.programming_verification_summary.total} 道输出已核对 · 共 ${t.programming_verification_summary.case_count} 组用例</p>`:''}<p>${esc(['needs_attention','interrupted'].includes(t.status)?'已停止执行，等待恢复':t.phase||'')}${t.activity&&['running','importing'].includes(t.status)?' · '+esc(t.activity):''}</p><p class="muted">组卷运行 ${elapsed(t)}${t.platform?.elapsed_seconds!=null?' · 平台上传与核对 '+duration(t.platform.elapsed_seconds):''} · ${t.rounds||0} 批组卷 · ${t.model_calls||0} 次累计模型调用${t.budget?' · 本轮 '+(t.run_model_calls||0)+' / '+t.budget.max_calls:''}</p>${t.platform?.coding_progress?`<p class="muted">${esc(codingProgressLabel(t.platform.coding_progress))}</p>`:''}${['completed','needs_attention'].includes(t.status)&&t.import_id?`<button class="secondary" data-agent-recheck="${esc(t.id)}">核对平台试卷，缺失则恢复</button>`:''}${['queued','running'].includes(t.status)?`<button class="secondary" data-agent-stop="${esc(t.id)}">停止当前任务</button>`:''}${t.can_resume?`<button class="secondary" data-agent-resume="${esc(t.id)}">继续当前任务（保留已有成果，增加一轮预算）</button>`:''}${t.message?`<p class="${t.status==='needs_attention'?'warning':'muted'}">${esc(t.message)}</p>`:''}${(t.draft_warnings||[]).map(w=>`<p class="warning">${esc(w)}</p>`).join('')}${t.draft_url&&/^https:\/\/www\.educoder\.net\/classrooms\//.test(t.draft_url)?`<a target="_blank" rel="noopener" href="${esc(t.draft_url)}" class="primary">打开头歌未发布试卷${t.platform?.name?'：'+esc(t.platform.name):''}</a>`:''}${(t.files||[]).map(f=>` <a href="/api/agent-tasks/${esc(t.id)}/files/${esc(f)}" download>${f==='assignment.xlsx'?'试卷 Excel':f==='judge-tests.zip'?'完整评测包':'完整题目'}</a>`).join('')}<details data-agent-decisions="${esc(t.id)}"><summary>查看 Agent 决策与检查记录</summary>${(t.events||[]).map(e=>`<p>第 ${e.round} 批 · ${esc(actions[e.action]||e.action)}：${esc(e.reason)}</p>${(e.issues||[]).filter(i=>i.severity!=='advisory').map(i=>`<p class="muted">${esc(i.message)}</p>`).join('')}`).join('')}${t.has_result?`<button class="secondary" data-agent-result="${esc(t.id)}">下载完整任务结果</button>`:''}</details></div>`;
 }
 let refreshing=null;
 function refresh(){
  if(!refreshing)refreshing=refreshOnce().finally(()=>{refreshing=null;});
  return refreshing;
 }
 async function refreshOnce(){
  const sequence=++refreshSequence;
  const data=await getTask('/api/agent-tasks');
  if(sequence!==refreshSequence)return;
  const tasks=data.tasks.filter(t=>t.purpose!=='development_test');
  const current=tasks.find(t=>t.id===currentTaskId)||tasks.find(t=>['queued','running','importing'].includes(t.status));
  const history=tasks.filter(t=>t.id!==current?.id);
  const openedHistory=new Set([...document.querySelectorAll('[data-agent-history][open]')].map(e=>e.dataset.agentHistory));
  const decisions=new Set([...document.querySelectorAll('[data-agent-decisions][open]')].map(e=>e.dataset.agentDecisions));
  $('agent-tasks').innerHTML=current?`<div class="agent-current"><h3>当前任务</h3>${taskCard(current)}</div>`:'';
  $('task-controls').hidden=!current;
  $('history-count').textContent=history.length||'';
  $('task-history-list').innerHTML=history.length?history.map(t=>`<details class="history-entry" data-agent-history="${esc(t.id)}" ${openedHistory.has(t.id)?'open':''}><summary><span class="history-title">${esc(t.request)}</span><span class="history-label">${esc(labels[t.status]||t.status)}</span></summary>${taskCard(t)}</details>`).join(''):'<div class="history-empty">暂无历史任务。先从一份新作业开始吧。</div>';
  document.querySelectorAll('[data-agent-decisions]').forEach(e=>{if(decisions.has(e.dataset.agentDecisions))e.open=true;});
  const active=data.tasks.some(t=>['queued','running','importing'].includes(t.status));$('agent-start').disabled=active;
  const stopButton=$('agent-stop-current'),controlNote=$('agent-control-note');
  const activeTask=data.tasks.find(t=>['queued','running','importing'].includes(t.status));
  if(stopButton){
   stopButton.hidden=!activeTask||!['queued','running'].includes(activeTask.status);
   stopButton.onclick=activeTask?()=>busy(stopButton,()=>stopTask(activeTask.id)):null;
  }
  if(controlNote)controlNote.textContent=activeTask?(activeTask.status==='importing'?'当前任务正在写入并核对平台草稿，请等待完成。':'已有任务正在执行；如需改要求，请先点击旁边的“停止当前任务”。'):'';
  if(active&&!timer)timer=setInterval(()=>refresh().catch(showAgentError),eventStream?10000:2500);
  if(!active&&timer){clearInterval(timer);timer=null;}
  document.querySelectorAll('[data-agent-recheck]').forEach(b=>b.onclick=()=>busy(b,async()=>{
   const r=await fetch('/api/agent-tasks/'+b.dataset.agentRecheck+'/recheck',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}',signal:AbortSignal.timeout(15000)});
   const data=await r.json();if(!r.ok)throw Error(data.error||'核对失败');await refresh();
  }));
  document.querySelectorAll('[data-agent-stop]').forEach(b=>b.onclick=()=>busy(b,async()=>{
   await stopTask(b.dataset.agentStop);
  }));
  document.querySelectorAll('[data-agent-resume]').forEach(b=>b.onclick=()=>busy(b,async()=>{
   const r=await fetch('/api/agent-tasks/'+b.dataset.agentResume+'/resume',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}',signal:AbortSignal.timeout(15000)});
   const data=await r.json();if(!r.ok)throw Error(data.error||'继续任务失败');
   currentTaskId=b.dataset.agentResume;
   status('已继续原任务，保留完成的题目和检查结果。');await refresh();
  }));
  document.querySelectorAll('[data-agent-result]').forEach(b=>b.onclick=async()=>{
   const t=await getTask('/api/agent-tasks/'+b.dataset.agentResult);
   const url=URL.createObjectURL(new Blob([JSON.stringify(t.result,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='agent-assignment.json';a.click();URL.revokeObjectURL(url);
  });
 }
 $('agent-start').onclick=async()=>{
  if(!$('agent-prompt').value.trim()){
   showAgentError(new Error('请先描述这次作业的课程、范围和题型要求。'));$('agent-prompt').focus();return;
  }
  $('agent-start').disabled=true;$('agent-tasks').insertAdjacentHTML('afterbegin','<p class="hint" id="agent-submitting">正在提交当前要求，马上显示任务进度…</p>');try{
  const created=await submitTask({prompt:$('agent-prompt').value,name:$('agent-name').value.trim()||('Agent作业-'+new Date().toISOString().replace(/[:.]/g,'-').slice(0,19)),classroom_url:$('agent-classroom').value.trim(),course:$('agent-course').value.trim(),execute:!$('agent-local').checked});
  currentTaskId=created.id;
  status('Agent 已接手任务，可在上方查看自动决策与交付结果。');
  }catch(e){showAgentError(e)}finally{const pending=$('agent-submitting');if(pending)pending.remove();await refresh().catch(showAgentError);}
 };
 document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh().catch(showAgentError);});
 window.addEventListener('focus',()=>refresh().catch(showAgentError));
 $('agent-refresh').onclick=()=>busy($('agent-refresh'),refresh);
 document.addEventListener('courseagent:new-assignment',()=>{currentTaskId=null;refresh().catch(showAgentError);});
 if(window.EventSource){
  eventStream=new EventSource('/api/agent-events');
  let scheduled=null;
  eventStream.addEventListener('progress',()=>{if(!scheduled)scheduled=setTimeout(()=>{scheduled=null;refresh().catch(showAgentError);},300);});
  // Legacy app.py has no SSE route; keep polling as a compatibility fallback.
  eventStream.onerror=()=>{if(eventStream?.readyState===EventSource.CLOSED){eventStream.close();eventStream=null;}};
 }
 refresh().catch(showAgentError);
})();
