let state, sources=[], beforePlan=null, dirty=false, catalogDirty=false;
const names={1:'单选题',2:'多选题',3:'判断题',4:'填空题',5:'简答题'};
const fields=['type','stem','options','answer','blanks','reference_answer','rubric','score','knowledge','explanation','source','source_refs'];
const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const snapshot=q=>Object.fromEntries(fields.map(f=>[f,q[f]??null]));
const status=(s,error=false)=>{$('status').textContent=s;$('status').style.color=error?'#a84738':'#717d68';const note=$('workspace-feedback');if(note){note.textContent=s;note.classList.toggle('error',error)}};
function changed(q){dirty=true;if(q){q.approved=false;delete q.approval_snapshot}status('有修改尚未保存。')}
async function api(path,payload){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});if(!r.ok)throw Error((await r.json()).error||'操作失败');return r}
async function busy(button,fn){button.disabled=true;try{await fn()}catch(e){status(e.message,true)}finally{button.disabled=button.id==='start-import'&&importActive}}
function selected(){return state.questions.filter(q=>q.selected)}
function programmingSelected(){return (state.programming_questions||[]).filter(q=>q.selected)}
function allSelected(){return [...selected(),...programmingSelected()]}
function summary(){const qs=allSelected(),counts=Object.keys(names).map(t=>`${names[t]} ${qs.filter(q=>q.type===+t).length}`).join(' · ')+` · 编程题 ${programmingSelected().length}`;$('summary').innerHTML=`<span><strong>${qs.length}</strong> 道已选</span><span><strong>${qs.filter(q=>q.approved).length}</strong> 道已确认</span><span><strong>${qs.reduce((n,q)=>n+Number(q.score||0),0)}</strong> 分</span><span class="muted">${counts}</span>`}
function sourceLink(ref){if(ref.url){if(!/^https?:\/\//i.test(ref.url))return '';return `<a href="${esc(ref.url)}" target="_blank" rel="noopener noreferrer">查看网络原文</a>`}const s=sources.find(s=>s.id===ref.document_id);if(!s)return '';const page=ref.page?` · 第 ${ref.page} 页`:ref.paragraph?` · 段落 ${ref.paragraph}`:'';return `<a href="/source/${esc(s.id)}${ref.page?'#page='+ref.page:''}" target="_blank" rel="noopener">${esc(s.name)}${page}</a>`}
function answerHTML(q){
 if(q.type===1||q.type===2){const options=q.options||[];let html=`<div class="options">${options.map((v,i)=>`<span>${String.fromCharCode(65+i)}</span><input aria-label="选项${String.fromCharCode(65+i)}" type="text" data-option="${i}" value="${esc(v)}"><button class="text" data-remove="${i}" aria-label="删除选项${String.fromCharCode(65+i)}">×</button>`).join('')}</div><button class="text" data-add-option>＋ 添加选项</button>`;
 if(q.type===1)html+=`<label>正确答案<select data-field="answer"><option value="">待填写</option>${options.map((v,i)=>{const a=String.fromCharCode(65+i);return `<option ${q.answer===a?'selected':''}>${a}</option>`}).join('')}</select></label>`;
 else html+=`<label>正确答案（可多选）</label><div class="row">${options.map((v,i)=>{const a=String.fromCharCode(65+i);return `<label class="check"><input type="checkbox" data-answer-letter="${a}" ${(q.answer||'').includes(a)?'checked':''}>${a}</label>`}).join('')}</div>`;
 return html;
 }
 if(q.type===3)return `<label>判断答案<select data-field="answer"><option value="">待填写</option><option ${q.answer==='正确'?'selected':''}>正确</option><option ${q.answer==='错误'?'selected':''}>错误</option></select></label>`;
 if(q.type===4)return `<label>各空标准答案（每行一个，最多 8 个）<textarea data-field="blanks">${esc((q.blanks||[]).join('\n'))}</textarea></label><p class="muted">题干使用 ____ 或（  ）表示每个空。当前每空导出一个标准答案，等价答案格式尚待头歌验证。</p>`;
 return `<label>参考答案<textarea data-field="reference_answer">${esc(q.reference_answer)}</textarea></label><label>评分要点<textarea class="rubric" data-field="rubric">${esc(q.rubric)}</textarea></label><p class="muted">简答题需要人工评分；评分要点与解析一起导出。</p>`;
}

function catalogText(){return (state.knowledge_catalog||[]).map(c=>`${c.group} | ${c.name} | ${c.aliases.join(', ')}`).join('\n')}
function renderCatalog(){if(!catalogDirty)$('knowledge-catalog').value=catalogText()}
function tagsHTML(q){
 const t=q.knowledge_tags||{},list=t.suggestions||[],ids=t.reviewed?(t.confirmed_ids||[]):(t.confirmed_ids?.length?t.confirmed_ids:list.map(s=>s.id));
 return `<p><strong>知识点标签：</strong>${t.reviewed?'教师已确认':'系统建议，待教师核对'}</p>${list.length?list.map(s=>`<details><summary>${esc(s.group)} / ${esc(s.name)} · 规则线索</summary>${s.evidence.map(e=>`<p class="muted">依据：${esc(e.label)}包含“${esc(e.keyword)}”；原文：${esc(e.excerpt)}</p>`).join('')}</details>`).join(''):'<p class="muted">未找到明确规则线索，不影响选题。可手动选择知识点，或保留未标注。</p>'}<details><summary>核对、修正或拒绝建议标签</summary><div>${(state.knowledge_catalog||[]).map(c=>`<label class="check"><input type="checkbox" data-tag-id="${esc(c.id)}" ${ids.includes(c.id)?'checked':''}>${esc(c.group)} / ${esc(c.name)}</label>`).join('')}</div><button class="secondary" data-confirm-tags>确认当前标签选择</button><p class="muted">可以取消全部勾选，确认此题暂无适用标签。标签审核与题目答案审核是两件事。</p></details>${t.reviewed?`<p class="muted">确认结果：${(state.knowledge_catalog||[]).filter(c=>(t.confirmed_ids||[]).includes(c.id)).map(c=>esc(c.name)).join('、')||'暂无适用标签'}</p>`:''}`;
}
function renderKnowledgeOverview(){
 const qs=selected();const unknown=qs.filter(q=>!q.knowledge_tags?.suggestions?.length&&!q.knowledge_tags?.reviewed).length;
 const rows=(state.knowledge_catalog||[]).map(c=>{const suggested=qs.filter(q=>q.knowledge_tags?.suggestions?.some(s=>s.id===c.id)).length,confirmed=qs.filter(q=>q.knowledge_tags?.reviewed&&q.knowledge_tags.confirmed_ids.includes(c.id)).length;return suggested||confirmed?`<tr><td>${esc(c.group)} / ${esc(c.name)}</td><td>${suggested}</td><td>${confirmed}</td></tr>`:''}).join('');
 $('knowledge-overview').innerHTML=`<p class="muted">当前已选 ${qs.length} 道题；${unknown} 道无规则线索且未核对。下表统计题数，一题可对应多个知识点；未确认的线索不计入教师确认覆盖。</p>${rows?`<table style="width:100%;text-align:left"><thead><tr><th>知识点</th><th>规则线索题数</th><th>教师确认题数</th></tr></thead><tbody>${rows}</tbody></table>`:''}`;
}
function render(){
 $('name').value=state.name;$('review-context').textContent=`正在查看：${state.name} · ${allSelected().length} 道已选题；请核对每题内容和答案，再勾选卡片底部的审核确认。`;summary();const type=+$('type-filter').value,query=$('question-query').value.trim().toLowerCase();
 const shown=state.questions.filter(q=>($('tag-filter').value==='all'||$('tag-filter').value==='pending'&&!q.knowledge_tags?.reviewed||$('tag-filter').value==='confirmed'&&q.knowledge_tags?.reviewed||$('tag-filter').value==='unknown'&&!q.knowledge_tags?.suggestions?.length)&&(!type||q.type===type)&&(!$('selected-filter').checked||q.selected)&&(!$('pending-filter').checked||!q.approved)&&(!query||(`${q.stem} ${q.knowledge}`).toLowerCase().includes(query)));
 $('questions').innerHTML=shown.map(q=>`<article class="question ${q.approved?'approved':''}" data-id="${esc(q.id)}"><div class="row"><label class="check"><input type="checkbox" data-field="selected" ${q.selected?'checked':''}>加入试卷</label><h3>${q.origin==='web_adapted'?(q.adaptation_basis==='web_knowledge'?'依据网页知识内容出题':'根据网络原题改编'):q.origin==='web'?'网络原题':q.source_number?'原题 '+q.source_number:'补充题'}</h3><span class="badge">${names[q.type]}</span>${q.origin==='supplement'?'<span class="badge supplement">依据课件补充</span>':''}</div><p class="muted">来源：${esc(q.source)} ${(q.source_refs||[]).map(sourceLink).join('；')}</p>${['web','web_adapted'].includes(q.origin)?`<details><summary>查看题目与答案的原文依据</summary>${(q.source_refs||[]).filter(r=>r.url).map(r=>`<p class="muted">${r.answer_evidence_segments?.length?'以下答案由多段已定位的原文组成。 ':''}获取时间：${esc(r.retrieved_at)} · ${r.answer_status==='rule_derived'?'改编答案为本地规则计算，待教师审核':r.answer_status==='model_derived'?'改编答案为模型推导，待教师审核':r.answer_status==='source_explicit'?'网页给出答案，正确性待审核':'未取得答案依据'}</p><pre style="white-space:pre-wrap">${['web_adapted','web_knowledge_drafted'].includes(r.method)?(r.method==='web_knowledge_drafted'?'这是依据网页知识内容出的题；以下引用的是知识原文，当前答案是':'这是改编题；以下引用的是原题，当前答案是')+(r.answer_status==='rule_derived'?'规则计算':'模型推导')+'，不能当作网页原答案。\n改编说明：'+esc(r.adaptation_reason)+'\n':''}${r.method==='web_knowledge_drafted'?'知识原文':'题目原文'}：${esc(r.stem_evidence)}\n答案原文：${esc(r.answer_evidence||'未找到')}</pre>`).join('')}</details>`:''}${q.warning&&!q.approved?`<p class="warning">${esc(q.warning)}</p>`:''}${q.selection_reason?`<p class="muted">推荐依据：${esc(q.selection_reason)}</p>`:''}${q.selected?`<label>换题原因<select data-replacement-reason><option value="">查看现有备选</option><option value="repetition">重复考点</option><option value="topic">超出教学范围</option><option value="answer">答案有疑问</option><option value="conditions">条件不完整</option></select></label><button class="secondary" data-alternatives>查看同题型备选题</button> <button class="secondary" data-search-replacement>按原因重新找题</button><div data-alternative-results></div>`:''}<div class="row"><label>题型<select data-field="type">${Object.keys(names).map(t=>`<option value="${t}" ${q.type===+t?'selected':''}>${names[t]}</option>`).join('')}</select></label><label>分值<input type="number" min="0.1" step="0.1" data-field="score" value="${esc(q.score)}"></label></div><div class="row"><label>教师标注难度（可选）<select data-field="teacher_difficulty">${[[0,'未标注'],[1,'基础'],[2,'适中'],[3,'困难']].map(([v,label])=>`<option value="${v}" ${Number(q.teacher_difficulty||0)===v?'selected':''}>${label}</option>`).join('')}</select></label><label>参考用时 <input type="number" data-field="estimated_minutes" min="1" max="10000" step="1" value="${esc(q.estimated_minutes??2)}"> 分钟</label></div><p class="muted">难度仅作教师标注；未标注不影响推荐。用时是参考估计，可按课堂情况修改。</p><label>题干<textarea class="stem" data-field="stem">${esc(q.stem)}</textarea></label>${answerHTML(q)}<label>知识点<input type="text" data-field="knowledge" value="${esc(q.knowledge)}"></label><div data-knowledge-tags style="margin:14px 0;padding:12px;background:#f4f6fb">${tagsHTML(q)}</div><label>解析<textarea data-field="explanation">${esc(q.explanation)}</textarea></label><label class="check approval"><input type="checkbox" data-field="approved" ${q.approved?'checked':''}>我已核对题目、答案、分值和出处，确认可用于本次作业</label></article>`).join('')||'<section class="panel muted">当前筛选条件下没有题目。</section>';
 if(typeof renderProgramming==='function')renderProgramming();renderPlan();renderCatalog();renderKnowledgeOverview();renderQuality();if(typeof reviewTaskCache!=='undefined')renderReviewTaskList();
}
function teachingGoalsInput(){
 const text=$('teaching-goals').value.trim();if(!text)return null;
 return text.split('\n').filter(l=>l.trim()).map(line=>{const parts=line.split('|');if(parts.length!==2)throw Error('教学目标每行使用“目标名称 | 关键词”的格式');return {name:parts[0].trim(),keywords:parts[1].split(/[,，、]/).map(s=>s.trim()).filter(Boolean)}});
}
function renderTeachingPlan(){
 const plan=state.plan?.spec?.teaching_plan;if(!plan)return;
 const qs=selected().concat(programmingSelected()),goals=plan.goals;
 const hits=q=>{
  const basis={question:Object.fromEntries(['title','description','knowledge'].map(k=>[k,q[k]||''])),goals:goals.map(g=>({id:g.id,name:g.name,keywords:g.keywords}))};
  const fit=q.course_fit||{},prior=fit.alignment_basis;
  const valid=prior&&Object.keys(basis.question).every(k=>prior.question?.[k]===basis.question[k])&&
   Array.isArray(prior.goals)&&prior.goals.length===goals.length&&prior.goals.every((g,i)=>
    g.id===goals[i].id&&g.name===goals[i].name&&JSON.stringify(g.keywords)===JSON.stringify(goals[i].keywords));
  const text=[q.stem,q.title,q.description,q.knowledge].filter(Boolean).join(' ').toLowerCase();
  return goals.flatMap(g=>{
   const m=valid&&(fit.goal_alignment||[]).find(m=>m.goal_id===g.id);
   if(m)return m.relation==='incidental'?[]:[{...g,kind:m.relation}];
   return g.keywords.some(w=>text.includes(w.toLowerCase()))?[{...g,kind:'keyword'}]:[];
  });
 };
 const unknown=qs.filter(q=>!hits(q).length).length;
 const patterns=new Map();for(const q of qs){const key=(q.stem||q.title||'').replace(/\s+/g,'').replace(/\d+(?:\.\d+)?/g,'#').toLowerCase();patterns.set(key,(patterns.get(key)||0)+1)}
 const repeats=[...patterns.values()].filter(n=>n>1).length;
 $('plan-result').insertAdjacentHTML('beforeend',`<section data-teaching-plan class="panel" style="margin-top:14px"><h3>本次教学目标与覆盖线索</h3><p class="muted">${esc(plan.note)} 分配题数为建议，一题可命中多目标；已纳入编程题完整题面；直接考查、应用与关键词线索分开显示，模型判断不等于教师确认覆盖。</p><table style="width:100%;text-align:left"><thead><tr><th>教学目标</th><th>建议题数</th><th>已选题线索</th></tr></thead><tbody>${goals.map(g=>{const matches=qs.flatMap(q=>hits(q).filter(h=>h.id===g.id));const n=matches.length;const details=[['direct','直接'],['application','应用'],['keyword','关键词']].map(([k,label])=>{const count=matches.filter(m=>m.kind===k).length;return count?label+' '+count:''}).filter(Boolean).join('、');return `<tr><td>${esc(g.name)}<details><summary>关键词与参考依据</summary><p>${esc(g.keywords.join('、'))}</p>${(g.reference_evidence||[]).map(r=>`<p class="muted">${esc(r.name)} ${r.page?'第'+esc(r.page)+'页':''}：${esc(r.excerpt)}</p>`).join('')||'<p class="muted">所选参考片段中未找到关键词，属于建议目标。</p>'}</details></td><td>${g.suggested_count}</td><td>${n?n+' 道（'+details+'）':'暂无匹配，请核对或换题'}</td></tr>`}).join('')}</tbody></table><p class="muted">${unknown} 道已选题暂无目标匹配；${repeats} 组题干在忽略数字后相同，建议核对是否重复考察。系统优先分散目标与数字变体，不为凑覆盖虚构题目。</p><button class="secondary" data-edit-goals>复制目标到编辑区</button><p class="muted">复制后可调整关键词，重新推荐生成新预览；保存前不会覆盖已保存的审核结果。</p></section>`);
}
$('plan-result').addEventListener('click',e=>{if(!e.target.hasAttribute('data-edit-goals'))return;$('teaching-goals').value=state.plan.spec.teaching_plan.goals.map(g=>g.name+' | '+g.keywords.join(',')).join('\n');$('teaching-goal-editor').open=true;$('teaching-goals').scrollIntoView({behavior:'smooth'});status('目标已复制，可以修改后重新推荐；当前题目保持原样。')});
function renderPlan(){
 const p=state.plan;if(!p){$('plan-result').innerHTML='';return}
 const qs=allSelected(),estimate=qs.reduce((n,q)=>n+Number(q.estimated_minutes??(q.kind==='programming'?20:2)),0),target=p.spec?.target_minutes;
 const counts=Object.entries(p.spec?.counts||{}).map(([t,wanted])=>{const actual=qs.filter(q=>q.type===+t).length,incomplete=p.diagnostics?.incomplete_by_type?.[t]||0;return `<tr><td>${esc(names[t])}</td><td>${wanted}</td><td>${actual}</td><td>${incomplete}</td></tr>`}).join('')+(p.spec?.programming_count?`<tr><td>编程题</td><td>${p.spec.programming_count}</td><td>${programmingSelected().length}</td><td>见编程题搜题记录</td></tr>`:'');
 const shortages=Object.entries(p.spec?.counts||{}).filter(([t,wanted])=>qs.filter(q=>q.type===+t).length!==wanted).map(([t,wanted])=>`<p class="warning">${esc(names[t])}需要 ${wanted} 道，当前选中 ${qs.filter(q=>q.type===+t).length} 道。请查看下方筛选说明。</p>`).join('')+(p.spec?.programming_count&&programmingSelected().length!==p.spec.programming_count?`<p class="warning">编程题需要 ${p.spec.programming_count} 道，当前选中 ${programmingSelected().length} 道。</p>`:'');
 const exclusions=p.diagnostics?.excluded;
 const complete=!shortages;
 const required=Object.entries(p.spec?.counts||{}).filter(([t,n])=>n>0).map(([t,n])=>`${n} 道${names[t]}`).concat(p.spec?.programming_count?[`${p.spec.programming_count} 道编程题`]:[]).join('、');
 $('plan-result').innerHTML=`<div class="hint"><strong>${complete?`已完成组卷：${qs.length} 道题`:`组卷未完成：要求 ${Object.values(p.spec?.counts||{}).reduce((a,b)=>a+b,0)+(p.spec?.programming_count||0)} 道，当前仅 ${qs.length} 道可用候选`}</strong><p class="muted">预计完成时间：约 ${estimate} 分钟，仅供参考。${target?`你的目标时间为 ${target} 分钟。`:''}用时来自各题的粗略估计，不影响审核、导出或导入。</p><p class="muted">难度要求由教师核对；未按导入时的默认难度筛选，也未调用模型评估难度。</p>${state.answer_matching?.matched?`<p>已从配套答案 PDF 匹配 ${state.answer_matching.matched} 道题的答案${state.answer_matching.algorithm_matched?`（含 ${state.answer_matching.algorithm_matched} 道算法参考答案）`:''}，尚需教师核对。</p>`:''}<table style="width:100%;text-align:left"><thead><tr><th>题型</th><th>要求</th><th>已选</th><th>范围内答案/内容不完整</th></tr></thead><tbody>${counts}</tbody></table>${shortages}${exclusions?`<p class="muted">本次筛选排除：未选资料 ${exclusions.source||0} 道，课件页码 ${exclusions.pages||0} 道，知识范围 ${exclusions.topics||0} 道，答案或内容不完整 ${exclusions.incomplete||0} 道。统计为推荐时的结果；可取消“只看已选”找到未选题，补全内容后重新推荐。</p>`:''}<p class="muted">${esc(p.engine)}</p><details><summary>查看处理过程</summary><ol>${p.trace.map(t=>`<li>${esc(t)}</li>`).join('')}</ol></details></div>`;
 $('plan-result').insertAdjacentHTML('afterbegin',`<p class="hint" id="recognized-requirements"><strong>已识别的作业要求：</strong>${esc(required)}。下表“已选”是实际取得的题目数量，不是要求数量。</p>`);
 renderTeachingPlan();renderWebReport();if(typeof renderProgrammingReport==='function')renderProgrammingReport();
}

function renderSources(){const checked=new Set([...document.querySelectorAll('[data-source]:checked')].map(e=>e.dataset.source));$('sources').innerHTML=sources.map(s=>`<div class="source-card"><label class="check"><input type="checkbox" data-source="${esc(s.id)}" ${checked.size===0||checked.has(s.id)?'checked':''}>${esc(s.name)}</label><span class="muted">${s.kind.toUpperCase()}${s.pages?' · '+s.pages+' 页':''} · ${esc(s.warning)}</span></div>`).join('')||'<p class="muted">请添加题目文档和课件。</p>';document.dispatchEvent(new Event('courseagent:sources-changed'));$('attach-material').disabled=false}
async function save(){if(catalogDirty)throw Error('知识点表尚未应用，请先点击“应用知识点表并重新识别”。');const old=state.questions.filter(q=>q.approved).length;state=await (await api('/api/save',state)).json();dirty=false;render();await refreshReviewTasks();status(old>state.questions.filter(q=>q.approved).length?'已保存；内容不完整或审核后改动的题目已撤销确认。':'进度已保存。')}
$('name').oninput=e=>{state.name=e.target.value;changed()};
['type-filter','selected-filter','pending-filter','tag-filter'].forEach(id=>$(id).onchange=render);$('question-query').oninput=render;
$('questions').addEventListener('input',e=>{
 const card=e.target.closest('[data-id]');if(!card)return;const q=state.questions.find(q=>q.id===card.dataset.id),field=e.target.dataset.field;
 if(e.target.hasAttribute('data-replacement-reason'))return;
 if(field==='approved'||e.target.dataset.tagId)return;
 if(e.target.dataset.option!==undefined)q.options[+e.target.dataset.option]=e.target.value;
 else if(e.target.dataset.answerLetter){const letters=new Set(q.answer||'');e.target.checked?letters.add(e.target.dataset.answerLetter):letters.delete(e.target.dataset.answerLetter);q.answer=[...letters].sort().join('')}
 else if(field)q[field]=e.target.type==='checkbox'?e.target.checked:field==='blanks'?e.target.value.split('\n'):e.target.type==='number'?Number(e.target.value):e.target.value;
 if(field==='type'){q.type=+q.type;q.answer='';q.blanks=[];q.reference_answer='';if(q.type===1||q.type===2)q.options=['','','',''];else q.options=[];changed(q);render();return}
 if(field==='teacher_difficulty'){q.teacher_difficulty=+q.teacher_difficulty;changed();renderPlan();return}
 if(field==='estimated_minutes'){changed();renderPlan();return}
 if(field==='selected'){changed();summary();renderPlan();renderKnowledgeOverview();renderQuality();return}
 if(field==='stem'||field==='knowledge'){q.knowledge_tags={reviewed:false,suggestions:[],confirmed_ids:[]};card.querySelector('[data-knowledge-tags]').innerHTML=tagsHTML(q);renderKnowledgeOverview();renderPlan();}
 changed(q);renderQuality();card.classList.remove('approved');card.querySelector('[data-field=approved]').checked=false;summary();
});
$('questions').addEventListener('change',async e=>{
 if(e.target.dataset.field!=='approved')return;
 const q=state.questions.find(q=>q.id===e.target.closest('[data-id]').dataset.id);
 if(!e.target.checked){changed(q);summary();return}
 const atReview=JSON.stringify(snapshot(q));
 try{const result=await (await api('/api/validate',{questions:[{...q,selected:true}]})).json();if(result.errors.length)throw Error(result.errors[0].error);if(atReview!==JSON.stringify(snapshot(q)))throw Error('题目已发生变化，请重新确认');q.approved=true;q.approval_snapshot=snapshot(q);dirty=true;e.target.closest('[data-id]').classList.add('approved');summary();status('已确认此题，请保存进度。')}
 catch(error){q.approved=false;e.target.checked=false;status(error.message,true)}
});
$('questions').addEventListener('click',e=>{const card=e.target.closest('[data-id]');if(!card)return;const q=state.questions.find(q=>q.id===card.dataset.id);if(e.target.hasAttribute('data-add-option')){if(q.options.length>=15){status('最多 15 个选项',true);return}q.options.push('');changed(q);render()}else if(e.target.dataset.remove!==undefined){if(q.options.length<=2){status('至少保留 2 个选项',true);return}q.options.splice(+e.target.dataset.remove,1);q.answer='';changed(q);render()}});
$('add-question').onclick=()=>{const q={id:'manual-'+crypto.randomUUID(),type:(+$('type-filter').value===6?1:+$('type-filter').value)||1,stem:'',source:'教师手动录入',source_refs:[],origin:'manual',options:['','','',''],answer:'',blanks:[],reference_answer:'',rubric:'',knowledge:'',explanation:'',score:2,teacher_difficulty:0,estimated_minutes:2,selected:true,approved:false};state.questions.push(q);changed(q);$('pending-filter').checked=false;$('question-query').value='';render();document.querySelector(`[data-id="${q.id}"]`).scrollIntoView({behavior:'smooth'})};
$('save').onclick=()=>busy($('save'),save);
$('validate').onclick=()=>busy($('validate'),async()=>{const result=await (await api('/api/validate',state)).json();$('issues').textContent=result.errors.map(e=>e.error).join('\n');status(result.errors.length?`有 ${result.errors.length} 道题需要修改。`:'已选题目内容格式通过检查；导出仍需逐题审核。',!!result.errors.length)});
$('export').onclick=()=>busy($('export'),async()=>{await save();const r=await api('/api/export',state),url=URL.createObjectURL(await r.blob()),a=document.createElement('a');a.href=url;a.download='已审核-在线考试.xlsx';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);status(programmingSelected().length?'已导出Excel。编程题仅写入勾选的最多4组用例；请导出完整评测包，在平台补齐用例并设置可见性。':'已导出已审核题目。')});
$('plan').onclick=()=>busy($('plan'),async()=>{const request={teaching_goals:teachingGoalsInput(),use_model:$('use-model').checked,prompt:$('prompt').value,topics:$('topics').value,source_mode:$('source-mode').value,allow_adaptation:$('allow-adaptation').checked,web_urls:$('web-urls').value.split('\n').map(s=>s.trim()).filter(Boolean),source_ids:[...document.querySelectorAll('[data-source]:checked')].map(e=>e.dataset.source),page_start:$('page-start').value?+$('page-start').value:null,page_end:$('page-end').value?+$('page-end').value:null};if(+$('difficulty').value)request.difficulty=+$('difficulty').value;if($('minutes').value)request.target_minutes=+$('minutes').value;if($('use-counts').checked){request.counts=Object.fromEntries([1,2,3,4,5].map(t=>[t,+$('count-'+t).value]));request.programming_count=+$('count-programming').value;}const draft=request.source_mode==='web'?await runWebPlan(request):await (await api('/api/plan',{document:state,request})).json();beforePlan=structuredClone(state);state=draft;dirty=true;await refreshReviewTasks();$('undo-plan').hidden=false;$('selected-filter').checked=true;render();status(state.plan.complete?'已推荐题目，尚未覆盖保存的试卷。请审核后保存。':'组卷未完成，当前只是部分候选；已显示具体题型缺口，请勿当作完整作业。',!state.plan.complete)});
$('undo-plan').onclick=()=>{if(beforePlan){state=beforePlan;beforePlan=null;dirty=true;render();$('undo-plan').hidden=true;status('已撤销推荐，恢复原来的题目选择。')}};
$('source-search').onclick=()=>busy($('source-search'),async()=>{const r=await (await api('/api/search',{query:$('source-query').value})).json();$('search-results').innerHTML=`<p class="muted">找到 ${r.total} 处，最多显示 40 处</p>`+r.matches.map(m=>`<div class="search-hit">${sourceLink(m)}<pre>${esc(m.text)}</pre></div>`).join('')});
$('upload').onchange=()=>busy($('plan'),async()=>{const file=$('upload').files[0];if(!file)return;if(file.size>16_000_000)throw Error('单个文件最多 16 MB');await save();const content=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=reject;reader.readAsDataURL(file)});const result=await (await api('/api/import-documents',{name:file.name,content})).json();state=result.document;sources=result.sources;renderSources();render();$('upload').value='';status('资料已解析；新题目处于待审核状态。')});
window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue=''}});
Promise.all([fetch('/api/review').then(r=>r.json()),fetch('/api/sources').then(r=>r.json())]).then(([doc,data])=>{state=doc;sources=data.sources;renderSources();render()}).catch(()=>status('无法读取本地数据，请确认服务已启动。',true));

fetch('/api/model-status').then(r=>r.json()).then(s=>{$('use-model').disabled=!s.configured;$('model-status').textContent=s.configured?'已配置 '+s.model+'；模型适配：'+(s.backend||'langchain')+'。网络提取本身使用模型；勾选后增加一次批量规划并缓存。允许改编时还会批量改编并复核。相关文本发送至配置的模型服务。':(s.error||'尚未配置模型，可继续使用文件题库规则筛选。')}).catch(()=>{$('use-model').disabled=true;$('model-status').textContent='无法读取模型配置。'});


fetch('/api/workflow').then(r=>r.json()).then(g=>{
 const order=['__start__'];let current='__start__';
 while(current!=='__end__'&&order.length<20){const edge=g.edges.find(e=>e.source===current);if(!edge)break;current=edge.target;order.push(current);}
 $('workflow-graph').innerHTML=order.map(id=>`<span class="badge">${esc(g.nodes.find(n=>n.id===id)?.label||id)}</span>`).join('<span aria-hidden="true">→</span>');
 $('workflow-note').textContent='后台使用 '+g.engine+' StateGraph；'+g.model_mode+'。';
}).catch(()=>{$('workflow-graph').textContent='无法读取组卷流程，请刷新页面。'});
const importLabels={queued:'准备导入',running:'浏览器操作中',completed:'已保存并核对',needs_attention:'需要人工核对'};
const stageLabels={preparing:'正在打开并填写建卷信息，尚未创建草稿',checking_existing:'正在检查历史试卷是否仍存在',draft_creation_started:'已开始创建草稿，操作中断需先核对平台',draft_created:'未发布草稿已创建',upload_started:'已开始上传，不能直接重试',imported:'Excel 已上传，正在配置编程题与核对答案',saved:'未发布试卷已保存'};
function codingProgressLabel(p){
 if(p.step==='repairing_persisted_visibility')return `正在自动修正「${p.title||'编程题'}」的 ${p.mismatches?.length||0} 组用例公开状态，保存后重新核对`;
 const steps={bulk_uploading_cases:`批量追加测试文件 ${p.case_count||0}/${p.case_total||0}`,checking_description:'检查题面显示',adding_cases:`补充用例栏 ${p.case_count||0}/${p.case_total||0}`,writing_case:`更新测试用例 ${p.case_index||0}/${p.case_total||0}`,case_unchanged:`用例 ${p.case_index||0}/${p.case_total||0} 一致，跳过修改`,saving_cases:'保存用例',reading_persisted_cases:'重新读取已保存的用例',cases_already_synced:'已有用例完整，跳过填写和保存',persisted_cases_already_verified:'已核对保存内容，跳过重复打开'};
 return `Excel 已上传 · 编程题已核对 ${p.completed||0}/${p.total||0} 道 · ${p.title||''}${steps[p.step]?' · '+steps[p.step]:''}`;
}
let importTimer=null,importActive=false;
function openManualWorkbench(){ document.dispatchEvent(new CustomEvent('courseagent:open-workbench',{detail:{section:'question-review'}}));$('manual-workbench').open=true; }
function showImportPanel(){ openManualWorkbench(); $('import-panel').scrollIntoView({behavior:'smooth',block:'start'}); }
$('go-import').onclick=showImportPanel;
async function refreshImports(){
 const response=await fetch('/api/import-jobs');if(!response.ok)throw Error('无法读取导入进度');const data=await response.json();
 $('import-jobs').innerHTML=data.jobs.length?data.jobs.map(j=>`<div class="source-card"><strong>${esc(j.name)} · ${esc(importLabels[j.status]||j.status)}</strong><p class="muted">${j.question_count} 道题 · ${j.total_score} 分 · 审核版本 ${j.review_version} · ${esc(j.course)}</p>${j.platform_stage?`<p>${esc(stageLabels[j.platform_stage]||j.platform_stage)}</p>`:''}${j.coding_progress?`<p class="muted">${esc(codingProgressLabel(j.coding_progress))}</p>`:''}${j.message?`<p class="${j.status==='needs_attention'?'warning':'muted'}">${esc(j.message)}</p>`:''}${j.draft_url&&/^https:\/\/www\.educoder\.net\/classrooms\//.test(j.draft_url)?`<a href="${esc(j.draft_url)}" target="_blank" rel="noopener">查看头歌未发布试卷</a>`:''}</div>`).join(''):'<p class="muted">尚无页面导入任务。此前的脚本测试记录保留在项目 outputs 文件夹中。</p>';
 const running=data.jobs.some(j=>j.status==='queued'||j.status==='running');
 importActive=running;$('start-import').disabled=running;
 if(running&&!importTimer)importTimer=setInterval(()=>refreshImports().catch(e=>status(e.message,true)),2500);
 if(!running&&importTimer){clearInterval(importTimer);importTimer=null;}
 return data;
}
$('refresh-imports').onclick=()=>busy($('refresh-imports'),refreshImports);
$('start-import').onclick=()=>busy($('start-import'),async()=>{
 const classroom_url=$('classroom-url').value.trim(),course=$('import-course').value.trim();
 if(!allSelected().length||allSelected().some(q=>!q.approved))throw Error('请先逐题审核所有已选题目，再导入。');
 await completeReview();
 const job=await(await api('/api/start-import',{version:state.version,classroom_url,course})).json();
 status(job.verifying?'题目已上传，正在重新核对和保存，不会重复上传。':job.reconciling?'正在检查头歌中的旧试卷，删除后会自动重新创建。':job.reused?(job.reuse_message||'存在本地历史任务，请查看原任务状态；这不代表平台草稿目前仍存在。'):(job.restarted?'上次在创建草稿前中断，正在用已保存题目重新导入。':'导入任务已开始，试卷会保持未发布状态。'),job.reused&&job.status==='needs_attention');
 await refreshImports();
});
refreshImports().catch(e=>status(e.message,true));

function showAlternatives(card,qs){
 card.querySelector('[data-alternative-results]').innerHTML=qs.length?qs.map(q=>`<div class="source-card"><strong>${esc(q.stem)}</strong><p class="muted">${esc(names[q.type])} · ${q.score} 分 · ${esc(q.source)} ${(q.source_refs||[]).map(sourceLink).join('；')}</p><details><summary>查看答案与解析</summary><p>${esc(q.type===4?(q.blanks||[]).join('；'):q.type===5?q.reference_answer:q.answer)}</p>${(q.options||[]).map((v,i)=>`<p>${String.fromCharCode(65+i)}. ${esc(v)}</p>`).join('')}<p>${esc(q.explanation)}</p></details><button class="secondary" data-replace-id="${esc(q.id)}">用这道题替换</button></div>`).join(''):'<p class="muted">本批未找到合适备选，原题保持不变。可以按原因继续找题。</p>';
}
$('questions').addEventListener('click',async e=>{
 const button=e.target.closest('[data-alternatives],[data-replace-id],[data-search-replacement]');if(!button)return;
 const card=button.closest('[data-id]'),id=card.dataset.id;
 await busy(button,async()=>{
  const reason=card.querySelector('[data-replacement-reason]').value;
  if(button.hasAttribute('data-alternatives')){
   const result=await(await api('/api/alternatives',{document:state,question_id:id,reason})).json();showAlternatives(card,result.questions);
  }else if(button.hasAttribute('data-search-replacement')){
   if(!reason)throw Error('请先选择换题原因');
   const input=JSON.stringify(state);const job=await(await api('/api/search-replacement',{document:state,question_id:id,reason})).json();status('正在按原因找备选题，原题与审核确认保留。');
   for(;;){
    const r=await fetch('/api/replacement-jobs/'+job.id),data=await r.json();if(!r.ok||data.status==='failed')throw Error(data.error||'换题搜索未完成');
    if(data.status==='completed'){
     if(JSON.stringify(state)!==input)throw Error('搜索期间题目发生变化，未覆盖当前编辑。请基于当前题目重新找备选。');
     const saved=await(await fetch('/api/review')).json();if(saved.version!==data.review_version)throw Error('其他页面已保存新进度，未覆盖当前作业。');
     state=data.result.document;dirty=true;render();const target=document.querySelector(`[data-id="${CSS.escape(id)}"]`);if(target)showAlternatives(target,data.result.questions);status(data.result.note);break;
    }
    await new Promise(resolve=>setTimeout(resolve,2000));
   }
  }else{
   state=await(await api('/api/replace-question',{document:state,question_id:id,replacement_id:button.dataset.replaceId})).json();dirty=true;render();status('已替换题目，题量保持不变，其他题目审核确认保留；新题需重新审核，尚未保存。');
  }
 });
});

function qualityBasis(){return JSON.stringify({request:state.plan?.request,spec:state.plan?.spec,questions:selected().map(q=>({id:q.id,...snapshot(q)})),programming_questions:programmingSelected().map(q=>({id:q.id,...programmingSnapshot(q)}))})}
function renderQuality(){
 const r=state.quality_report;if(!r){$('quality-result').innerHTML='<p class="muted">尚未检查当前整卷。</p>';return}
 const stale=r.client_basis!==qualityBasis();
 $('quality-result').innerHTML=`${stale?'<p class="warning">题目或选择已变化，以下结果已过期，请重新检查。</p>':''}<p class="muted">${esc(r.note)} ${r.model_used?(r.cache_hit?'内容检查复用缓存。':'已完成一次批量内容检查。'):'本次为规则检查，未完成模型内容检查。'}</p>${r.model_error?`<p class="warning">${esc(r.model_error)}</p>`:''}${r.issues.length?r.issues.map(i=>`<div class="source-card"><strong>${esc({format:'内容格式',count:'题型数量',repetition:'重复考察',answer_leak:'答案提示',coverage:'目标覆盖',topic:'主题匹配',conditions:'题目条件',answer:'答案核对'}[i.kind]||i.kind)}</strong><p>${esc(i.message)}</p><p class="muted">${i.method==='model'?'模型建议，需教师核对':'规则线索'}</p>${i.question_ids.map(id=>`<button class="text" data-quality-question="${esc(id)}">定位题目 ${esc(id.slice(-8))}</button>`).join('')}</div>`).join(''):'<p>未发现具体问题；仍需逐题审核，规则检查不代表内容全部正确。</p>'}`;
}
$('check-quality').onclick=()=>busy($('check-quality'),async()=>{
 const input=qualityBasis();const result=await(await api('/api/exam-quality',{document:state,use_model:$('quality-use-model').checked})).json();
 if(input!==qualityBasis())throw Error('检查期间题目发生变化，请重新检查');state.quality_report={...result,client_basis:input};dirty=true;renderQuality();status('整卷检查已完成，建议显示在检查区，题目与审核确认保留。');
});
$('quality-result').onclick=e=>{const id=e.target.dataset.qualityQuestion;if(!id)return;$('type-filter').value=state.programming_questions?.some(q=>q.id===id)?'6':'0';$('tag-filter').value='all';$('pending-filter').checked=false;$('question-query').value='';$('selected-filter').checked=true;render();document.querySelector(`[data-id="${CSS.escape(id)}"],[data-programming-id="${CSS.escape(id)}"]`)?.scrollIntoView({behavior:'smooth',block:'center'})};

const reviewLabels={awaiting_review:'等待教师审核',reviewed:'已完成审核'};
let reviewTaskCache=[];
function renderReviewTaskList(){
 const named=reviewTaskCache.filter(t=>t.saved_name),legacy=reviewTaskCache.filter(t=>!t.saved_name&&t.id!==state?.review_task_id);
 const row=t=>`<div class="source-card"><strong>${esc(t.saved_name||t.name)}</strong><p class="muted">${t.question_count} 道题${t.created_at?' · '+esc(new Date(t.created_at).toLocaleString('zh-CN')):''}</p>${t.request?`<p class="muted">${esc(t.request)}</p>`:''}<button class="secondary" data-restore-task="${esc(t.id)}">恢复此方案</button></div>`;
 $('review-tasks').innerHTML=(named.length?named.map(row).join(''):'<p class="muted">尚未另存方案。当前作业使用“保存进度”即可，不需要另存。</p>')+(legacy.length?`<details id="review-history"><summary>找回早期推荐记录（${legacy.length} 条）</summary><p class="muted">这些是后台保留的早期组卷结果，仅供需要时找回。</p>${legacy.map(row).join('')}</details>`:'');
}
async function refreshReviewTasks(){
 const r=await fetch('/api/review-tasks');if(!r.ok)throw Error('无法读取审核任务');const data=await r.json();reviewTaskCache=data.tasks;renderReviewTaskList();
}
$('refresh-review-tasks').onclick=()=>busy($('refresh-review-tasks'),refreshReviewTasks);
async function completeReview(){
 if(!allSelected().length||allSelected().some(q=>!q.approved))throw Error('请先逐题核对所有已选题目，并勾选卡片底部的审核确认。');
 if(dirty)await save();
 await api('/api/complete-review',{version:state.version});
 status('审核已完成，可以导出或导入当前作业。');
}
$('resume-review').onclick=()=>busy($('resume-review'),async()=>{await completeReview();showImportPanel()});
$('save-scheme').onclick=()=>busy($('save-scheme'),async()=>{
 const name=$('scheme-name').value.trim();if(!name)throw Error('请填写方案名称');if(dirty)await save();
 await api('/api/save-scheme',{version:state.version,name});await refreshReviewTasks();status('已另存方案，当前作业保持不变。');
});
$('review-tasks').onclick=e=>{const id=e.target.dataset.restoreTask;if(!id)return;busy(e.target,async()=>{
 if(id===state?.review_task_id){showReviewContent();return}
 if(dirty)throw Error('当前有未保存修改，请先保存或撤销后再打开其他任务。可直接在当前作业区继续审核。');
 state=await(await api('/api/restore-review',{task_id:id,version:state.version})).json();dirty=true;beforePlan=null;$('undo-plan').hidden=true;render();showReviewContent();status(selected().length?'已打开任务题目，请逐题核对，勾选确认并保存，再点击“完成审核”。':'此任务没有选中题目，请调整组卷要求或补全答案后重新推荐。',!selected().length);
})};
refreshReviewTasks().catch(e=>status(e.message,true));

$('knowledge-catalog').oninput=()=>{catalogDirty=true;dirty=true;status('知识点表已修改，请应用后再保存。')};
$('apply-knowledge').onclick=()=>busy($('apply-knowledge'),async()=>{
 const catalog=$('knowledge-catalog').value.split('\n').filter(l=>l.trim()).map(line=>{const parts=line.split('|');if(parts.length!==3)throw Error('每行使用“分组 | 知识点 | 关键词”的格式');return {group:parts[0].trim(),name:parts[1].trim(),aliases:parts[2].split(/[,，、]/).map(s=>s.trim()).filter(Boolean)}});
 const preview={...state,knowledge_catalog:catalog};state=await(await api('/api/annotate-knowledge',preview)).json();catalogDirty=false;dirty=true;render();status('已更新本地标签建议，原题目和答案保持原样；请核对并保存。');
});
$('questions').addEventListener('change',e=>{
 if(!e.target.dataset.tagId)return;const card=e.target.closest('[data-id]'),q=state.questions.find(q=>q.id===card.dataset.id);
 q.knowledge_tags.confirmed_ids=[...card.querySelectorAll('[data-tag-id]:checked')].map(e=>e.dataset.tagId);q.knowledge_tags.reviewed=false;changed();renderKnowledgeOverview();
});
$('questions').addEventListener('click',e=>{
 if(!e.target.hasAttribute('data-confirm-tags'))return;const card=e.target.closest('[data-id]'),q=state.questions.find(q=>q.id===card.dataset.id);
 if(!q.knowledge_tags?.basis){status('题目已修改，请先应用知识点表重新识别，再确认标签。',true);return}
 q.knowledge_tags.confirmed_ids=[...card.querySelectorAll('[data-tag-id]:checked')].map(e=>e.dataset.tagId);q.knowledge_tags.reviewed=true;dirty=true;card.querySelector('[data-knowledge-tags]').innerHTML=tagsHTML(q);renderKnowledgeOverview();status('已确认此题知识标签，请保存进度；题目答案仍需单独审核。');
});

function showReviewContent(){
 $('type-filter').value='0';$('tag-filter').value='all';$('pending-filter').checked=false;$('selected-filter').checked=true;$('question-query').value='';$('issues').textContent='';render();
 openManualWorkbench(); $('question-review').scrollIntoView({behavior:'smooth',block:'start'});
 status(allSelected().length?'已显示当前全部已选题目，请在每题底部勾选审核确认。':'当前没有选中题目，请重新推荐；取消“只看已选”可查看题库。',!allSelected().length);
}
$('show-current-review').onclick=showReviewContent;

function renderWebReport(){
 const w=state.web_search;if(!w||state.plan?.engine?.indexOf('网络')<0)return;
 const f=w.fill_report;
 if(f){const missing=Object.entries(state.plan.spec.counts||{}).filter(([t,n])=>selected().filter(q=>q.type===+t).length<n).map(([t,n])=>`${names[t]}还缺 ${n-selected().filter(q=>q.type===+t).length} 道`).join('；');$('plan-result').insertAdjacentHTML('beforeend',`<div data-fill-report style="margin-top:12px"><p>${esc(missing&&!Object.keys(f.missing||{}).length?'当前已选数量不足，可保留现有题目继续补题。':f.reason)}</p>${missing?`<p class="warning">${esc(missing)}。已通过的题目继续保留。</p>`:''}<p class="muted">补搜 ${f.search_rounds}/${f.limits.search_rounds} 轮；改编 ${f.adaptation_rounds}/${f.limits.adaptation_rounds} 轮；整理与改编模型调用 ${w.model_calls}/${f.limits.model_calls} 次。${f.failed_sources?`有 ${f.failed_sources} 个改编任务未通过，已记录原因并换来源。`:''}预算是调用次数上限，不代表费用金额；缓存复用不计模型调用。${w.previous_model_calls?`此前补题批次用了 ${w.previous_model_calls} 次整理与改编调用，本批预算重新计数。`:''}${state.plan.spec.short_answer_kind==='algorithm_design'?'':'覆盖范围与推导深度仍需教师核对。'}</p>${missing?'<button data-continue-web>继续补题（保留当前已选题）</button><p class="muted">再开一批搜索与出题预算，可能产生模型费用；只补缺少题型，当前已选题及审核确认保留。</p>':''}</div>`);}
 $('plan-result').insertAdjacentHTML('beforeend',`<details style="margin-top:12px"><summary>网络搜题来源与排除记录</summary><p>读取 ${w.pages.length} 页，获得 ${w.knowledge_sources?.length||0} 段可核对知识素材，取得 ${w.candidate_count} 道候选${w.adaptation_count?'（含 '+w.adaptation_count+' 道改编或依据知识出题）':''}；本次整理、改编与复核模型调用 ${w.model_calls} 次，缓存命中 ${w.cache_hits} 次。未找到的题目会保留缺口。</p><p>查询：${esc(w.queries.join('；'))}</p>${w.events.map(e=>`<div class="source-card"><strong>${esc(e.title||e.query||'候选检查')}</strong>${e.url?sourceLink(e):''}<p class="muted">${esc({read:'正文读取成功',read_failed:'正文读取失败',search_failed:'搜索失败',adaptation_rejected:'改编题未通过检查',adaptation_failed:'改编未完成',candidate_rejected:'候选题未通过证据或题型检查',extract_failed:'题目提取失败'}[e.status]||e.status)} · ${esc(e.reason)}</p></div>`).join('')}</details>`);
}
$('plan-result').addEventListener('click',e=>{
 if(!e.target.hasAttribute('data-continue-web'))return;
 busy(e.target,async()=>{
  const p=state.plan;if(!p)throw Error('请先推荐题目');
  const request={prompt:p.request,source_mode:'web',allow_adaptation:$('allow-adaptation').checked,use_model:false,continue_web:true,
   locked_ids:selected().map(q=>q.id),programming_count:p.spec.programming_count||0,counts:p.spec.counts,topics:p.spec.topics.join('、'),
   difficulty:p.spec.difficulty,target_minutes:p.spec.target_minutes,source_ids:p.spec.source_ids,
   page_start:p.spec.page_start,page_end:p.spec.page_end,
   teaching_goals:p.spec.teaching_plan?.goals.map(g=>({name:g.name,keywords:g.keywords}))};
  const draft=await runWebPlan(request);beforePlan=structuredClone(state);state=draft;dirty=true;$('undo-plan').hidden=false;render();
  status(state.plan.complete?'缺少题型已补齐，当前已选题保留；新增题请逐题审核。':'本批仍有缺口，已保留当前题目和具体原因，可继续补题。',!state.plan.complete);
 });
});
let webRunning=false;
async function runWebPlan(request){
 if(webRunning)throw Error('网络搜题正在进行');
 webRunning=true;const input=structuredClone(state);
 try{
  const job=await(await api('/api/web-plan',{document:input,request})).json();
  localStorage.setItem('courseagent:web-job:v1',job.id);recoverWeb.hidden=false;
  return await waitWebJob(job.id,JSON.stringify(input));
 }finally{webRunning=false;recoverWeb.hidden=!localStorage.getItem('courseagent:web-job:v1')}
}
async function waitWebJob(id,original){
 for(;;){
  const r=await fetch('/api/web-jobs/'+id);const job=await r.json();if(!r.ok)throw Error(job.error||'无法读取搜题任务');
  $('web-progress').textContent=job.phase;
  if(job.status==='failed'){localStorage.removeItem('courseagent:web-job:v1');throw Error(job.error)}
  if(job.status==='completed'){
   if(JSON.stringify(state)!==original)throw Error('搜题期间你修改了当前作业，结果已保留；请保存修改后通过“找回网络搜题结果”加载，避免覆盖。');
   const current=await(await fetch('/api/review')).json();if(current.version!==job.review_version)throw Error('其他页面已保存新进度，搜题结果已保留在历史记录中，请刷新后找回。');
   localStorage.removeItem('courseagent:web-job:v1');return job.result;
  }
  await new Promise(resolve=>setTimeout(resolve,2000));
 }
}
const recoverWeb=document.createElement('button');recoverWeb.className='secondary';recoverWeb.textContent='找回网络搜题结果';recoverWeb.hidden=!localStorage.getItem('courseagent:web-job:v1');$('web-progress').after(recoverWeb);
recoverWeb.onclick=()=>busy(recoverWeb,async()=>{
 if(webRunning)throw Error('当前网络搜题仍在进行，请等待结果');
 if(dirty)throw Error('请先保存或撤销当前修改，再找回搜题结果');
 const id=localStorage.getItem('courseagent:web-job:v1');if(!id)throw Error('没有待找回的搜题任务');
 const result=await waitWebJob(id,JSON.stringify(state));
 if(result.version!==state.version)throw Error('当前审核进度已经变化，旧搜题结果保留在历史记录中，请通过历史方案找回');
 beforePlan=structuredClone(state);state=result;dirty=true;render();showReviewContent();recoverWeb.hidden=true;
});

fetch('/api/observability').then(r=>r.json()).then(s=>{
 $('trace-status').textContent='流程追踪：已保存本地节点耗时、数量与模型用量。'+(s.enabled&&s.configured&&s.sdk_installed?'LangSmith 已配置；云端连接结果以任务记录为准。':'LangSmith 云端追踪未启用或未配置；可通过本地 langsmith-config.local.json 配置。')+' 不上传题目或资料正文。'+(s.transport_error||'');
}).catch(()=>{$('trace-status').textContent='暂时无法读取追踪状态。'});
