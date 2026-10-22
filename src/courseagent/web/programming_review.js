// Separate data and review cards for the online-exam programming worksheet.
const programmingFields=['title','description','knowledge','score','difficulty','time_limit_seconds','languages','author_username','test_cases','explanation','reference_code','source','source_refs','public_examples','judge_contract','description_includes_examples','description_format'];
const programmingSnapshot=q=>structuredClone(Object.fromEntries([...programmingFields.filter(f=>!['description_includes_examples','description_format'].includes(f)||Object.hasOwn(q,f)),...(Object.hasOwn(q,'io_contract')?['io_contract']:[])].map(f=>[f,q[f]??null])));
const programmingLanguages=['C语言','C','C++','Python','Java','JavaScript','Ruby'];
function programmingText(label,field,value,code=false){return `<label>${label}<textarea data-programming-field="${field}" ${code?'spellcheck="false" style="font-family:monospace;min-height:140px"':''}>${esc(value)}</textarea></label>`}
function renderProgramming(){
 $('programming-import-note').hidden=!programmingSelected().length;$('start-import').disabled=importActive;
 const items=state.programming_questions||[],query=$('question-query').value.trim().toLowerCase(),type=+$('type-filter').value;
 const shown=items.filter(q=>(!type||type===6)&&(!$('selected-filter').checked||q.selected)&&(!$('pending-filter').checked||!q.approved)&&(!query||`${q.title} ${q.description} ${q.knowledge}`.toLowerCase().includes(query)));
 $('programming-summary').textContent=`编程题：已选 ${programmingSelected().length} 道，已确认 ${programmingSelected().filter(q=>q.approved).length} 道。标签状态筛选仅用于普通题；此处按题型、已选、审核状态及搜索内容筛选。`;
 $('programming-questions').innerHTML=shown.map(q=>`<article class="panel programming-question ${q.approved?'approved':''}" data-programming-id="${esc(q.id)}">
 <div class="row"><h3>${esc(q.title||'未命名编程题')}</h3><span class="badge">在线考试编程题</span><label class="check"><input type="checkbox" data-programming-field="selected" ${q.selected?'checked':''}>加入试卷</label><button class="text" data-remove-programming>移除题目</button></div>
 <p class="muted">来源：${esc(q.source||'待补充')} ${(q.source_refs||[]).map(sourceLink).join('；')}</p>
 ${q.source_metadata?.difficulty?`<p class="muted">原站难度：${esc(q.source_metadata.difficulty)} · 知识标签：${esc((q.source_metadata.tags||[]).join('、'))}。原站难度作为选题参考，与本课程难度标注分别保留。</p>`:''}
 ${q.source_reference?`<p class="muted">参考解法：${q.source_reference.status==='official_editorial'?'公开官方题解':'公开题解'} · ${sourceLink({url:q.source_reference.url})} · ${q.execution_verification?.passed?'已完成执行交叉核对':'等待执行核对'}。</p>`:''}
 ${q.origin==='web_programming_adapted'?'<p class="hint">依据网页原题或知识改编。题目、评测用例及可选参考代码可能包含模型生成内容，不能当作网页原答案。</p>':''}
 ${(q.source_refs||[]).some(r=>r.stem_evidence)?`<details><summary>查看编程题原文依据</summary>${(q.source_refs||[]).filter(r=>r.stem_evidence).map(r=>`<p class="muted">获取时间：${esc(r.retrieved_at)}；${r.answer_status==='model_derived'?'改编及预期输出可能为模型推导，待教师核对':'原文摘录仍需核对，不能替代用例确认'}</p><pre style="white-space:pre-wrap">${esc(r.stem_evidence)}</pre>`).join('')}</details>`:''}
 <label>任务名称<input type="text" data-programming-field="title" value="${esc(q.title)}"></label>
 ${programmingText('题目描述（请包含输入格式、输出格式、数据范围与约束）','description',q.description)}
 <div class="row"><label>分值<input type="number" min="0.1" step="0.1" data-programming-field="score" value="${esc(q.score)}"></label>
 <label>教师标注难度<select data-programming-field="difficulty"><option value="0" ${!q.difficulty?'selected':''}>待标注</option>${[[1,'基础'],[2,'适中'],[3,'困难']].map(([n,label])=>`<option value="${n}" ${q.difficulty===n?'selected':''}>${label}</option>`).join('')}</select></label>
 <label>运行时限（秒）<input type="number" min="1" step="1" data-programming-field="time_limit_seconds" value="${esc(q.time_limit_seconds)}"></label></div>
 <label>知识点<input type="text" data-programming-field="knowledge" value="${esc(q.knowledge)}"></label>
 <label>来源说明<input type="text" data-programming-field="source" value="${esc(q.source)}"></label>
 <h4>语言与初始代码</h4>${(q.languages||[]).map((item,i)=>`<div class="source-card"><label>语言 ${i+1}<select data-language-index="${i}" data-language-field="language">${programmingLanguages.map(l=>`<option ${item.language===l?'selected':''}>${l}</option>`).join('')}</select></label><label>学员初始代码<textarea spellcheck="false" style="font-family:monospace" data-language-index="${i}" data-language-field="starter_code">${esc(item.starter_code)}</textarea></label><button class="text" data-remove-language="${i}">移除此语言</button></div>`).join('')}<button class="secondary" data-add-language>添加语言（最多4组）</button>
 <h4>公开样例（学生可见）</h4><p class="muted">公开样例会追加到 Excel 题目描述，不占评测用例栏。</p>
 ${(q.public_examples||[]).map((c,i)=>`<div class="source-card"><strong>公开样例 ${i+1}</strong><div class="grid"><label>输入<textarea data-example-index="${i}" data-example-field="input">${esc(c.input)}</textarea></label><label>输出<textarea data-example-index="${i}" data-example-field="output">${esc(c.output)}</textarea></label></div><button class="text" data-remove-example="${i}">移除此样例</button></div>`).join('')}<button class="secondary" data-add-example>添加公开样例</button>
 <h4>评测用例（用于判定学生代码）</h4><p class="muted" data-case-summary>共 ${(q.test_cases||[]).length} 组，公开自测 ${(q.test_cases||[]).filter(c=>c.visibility==='public').length} 组，内部测试 ${(q.test_cases||[]).filter(c=>c.visibility!=='public').length} 组；已勾选写入Excel ${(q.test_cases||[]).filter(c=>c.excel_selected!==false).length} 组。</p><p class="muted">用例数量可自定；每组可以选择公开自测或内部测试。逐组核对输出依据后确认；模型复核不等于实际运行验证。当前 Excel 模板只有4组输入输出栏且没有可见性栏；勾选1至4组写入Excel，其余用例通过评测包完整导出，在平台补充并设置可见性。运行时限指程序执行时间。</p>
 ${(q.test_cases||[]).map((c,i)=>`<div class="source-card"><strong>用例 ${i+1}</strong><div class="row"><label>平台可见性<select data-case-index="${i}" data-case-field="visibility"><option value="public" ${c.visibility==='public'?'selected':''}>公开自测（学生可见）</option><option value="hidden" ${c.visibility!=='public'?'selected':''}>内部测试（学生不可见）</option></select></label><label class="check"><input type="checkbox" data-case-index="${i}" data-case-field="excel_selected" ${c.excel_selected!==false?'checked':''}>写入Excel（最多4组）</label></div><div class="grid"><label>输入<textarea spellcheck="false" data-case-index="${i}" data-case-field="input">${esc(c.input)}</textarea></label><label>预期输出<textarea spellcheck="false" data-case-index="${i}" data-case-field="output">${esc(c.output)}</textarea></label></div><label>测试目的（覆盖哪些边界或错误）<input type="text" data-case-index="${i}" data-case-field="purpose" value="${esc(c.purpose||'')}"></label><label>预期输出依据（原文位置、逐步推导或教师核对）<textarea data-case-index="${i}" data-case-field="output_basis">${esc(c.output_basis||'')}</textarea></label><label class="check"><input type="checkbox" data-case-index="${i}" data-case-field="verified" ${c.verified?'checked':''}>我已核对此用例的输入合法性和预期输出</label><button class="text" data-remove-case="${i}">移除此用例</button></div>`).join('')}<button class="secondary" data-add-case>添加评测用例</button>
 <details><summary>二叉树标准输入与固定算法用例工具</summary><p class="muted">按空格分隔的整数/null重建题面与8组用例，统一队列层序规则。不执行网页或模型代码。会替换现有题面、用例和初始代码，参考代码清空，需重新审核。</p><label>任务<select data-tree-task>${[['level_order','层序遍历'],['preorder','前序遍历'],['inorder','中序遍历'],['postorder','后序遍历'],['max_depth','最大深度'],['min_depth','最小深度'],['invert','翻转二叉树'],['leaf_count','叶子计数'],['node_count','节点计数']].map(([value,label])=>`<option value="${value}" ${q.judge_contract?.task===value?'selected':''}>${label}</option>`).join('')}</select></label><button class="secondary" data-rebuild-tree>重建题面和8组用例</button>${q.judge_contract?'<button class="text" data-remove-contract>解除固定契约，改为人工核对</button><p class="muted">当前启用固定契约：输入合法性与预期输出会由本地算法复查；修改题面格式需重建契约或解除契约。</p>':''}</details>
 ${programmingText('参考代码（可选；留空也能审核导出，不参与用例确认）','reference_code',q.reference_code,true)}
 ${programmingText('题目解析与评分说明','explanation',q.explanation)}
 <label class="check approval"><input type="checkbox" data-programming-field="approved" ${q.approved?'checked':''}>我已核对题意、约束、公开样例、语言、评测用例及其输出依据、分值和出处</label>
 </article>`).join('')||'<p class="muted">当前没有可显示的编程题。可新增题目或导入 JSON；题目不会自动加入已保存作业。</p>';
}
function renderProgrammingReport(){
 const r=state.programming_search;if(!r||!state.plan?.spec.programming_count)return;
 const missing=Math.max(0,state.plan.spec.programming_count-programmingSelected().length);
 $('plan-result').insertAdjacentHTML('beforeend',`<div class="hint" style="margin-top:12px"><strong>在线考试编程题搜题记录</strong><p>${esc(r.reason)}</p><p class="muted">搜题 ${r.search_rounds}/${r.limits.search_rounds} 轮，读取 ${r.pages}/${r.limits.pages} 页；模型整理与复核 ${r.model_calls}/${r.limits.model_calls} 次，缓存命中 ${r.cache_hits} 次。编程题预算单独计数；未执行代码。难度留给教师标注。</p>${missing&&$('source-mode').value==='web'?'<button data-continue-web>继续补编程题（保留已选题）</button>':''}<details><summary>查询与候选排除记录</summary><p>${esc(r.queries.join('；'))}</p>${r.events.map(e=>`<p>${e.url?sourceLink(e)+' · ':''}${esc(e.reason)}</p>`).join('')}</details></div>`);
}
function programmingChanged(q,card){const counts=card?.querySelector('[data-case-summary]');if(counts)counts.textContent=`共 ${(q.test_cases||[]).length} 组，公开自测 ${(q.test_cases||[]).filter(c=>c.visibility==='public').length} 组，内部测试 ${(q.test_cases||[]).filter(c=>c.visibility!=='public').length} 组；已勾选写入Excel ${(q.test_cases||[]).filter(c=>c.excel_selected!==false).length} 组。`;changed(q);card?.classList.remove('approved');const checkbox=card?.querySelector('[data-programming-field="approved"]');if(checkbox)checkbox.checked=false;summary();renderQuality();$('programming-summary').textContent=`编程题：已选 ${programmingSelected().length} 道，已确认 ${programmingSelected().filter(q=>q.approved).length} 道。`}
$('programming-questions').addEventListener('input',e=>{
 const card=e.target.closest('[data-programming-id]');if(!card)return;const q=(state.programming_questions||[]).find(q=>q.id===card.dataset.programmingId),field=e.target.dataset.programmingField;
 if(field==='approved')return;
 if(e.target.dataset.languageIndex!==undefined)q.languages[+e.target.dataset.languageIndex][e.target.dataset.languageField]=e.target.value;
 else if(e.target.dataset.caseIndex!==undefined){const c=q.test_cases[+e.target.dataset.caseIndex],f=e.target.dataset.caseField;c[f]=e.target.type==='checkbox'?e.target.checked:e.target.value;if(!['verified','visibility','excel_selected'].includes(f)){c.verified=false;card.querySelector(`[data-case-index="${e.target.dataset.caseIndex}"][data-case-field="verified"]`).checked=false}}
 else if(e.target.dataset.exampleIndex!==undefined)q.public_examples[+e.target.dataset.exampleIndex][e.target.dataset.exampleField]=e.target.value;
 else if(field)q[field]=e.target.type==='checkbox'?e.target.checked:['score','difficulty','time_limit_seconds'].includes(field)?Number(e.target.value):e.target.value;
 else return;
 if(field==='selected'){changed();summary();renderProgramming();renderQuality();renderPlan();return}
 if(field==='description')for(const c of q.test_cases||[])c.verified=false;
 if(field==='description')card.querySelectorAll('[data-case-field="verified"]').forEach(el=>el.checked=false);
 programmingChanged(q,card);
 if(['title','description','knowledge'].includes(field))renderPlan();
});
$('programming-questions').addEventListener('change',async e=>{
 if(e.target.dataset.programmingField!=='approved')return;const card=e.target.closest('[data-programming-id]'),q=state.programming_questions.find(q=>q.id===card.dataset.programmingId);
 if(!e.target.checked){programmingChanged(q,card);return}
 const before=JSON.stringify(programmingSnapshot(q));
 try{
  if(![1,2,3].includes(q.difficulty))throw Error('请先根据课堂情况标注编程题难度，再确认审核。');
  for(const [i,c] of (q.test_cases||[]).entries())if(!c.verified||!c.purpose?.trim()||!c.output_basis?.trim())throw Error(`请填写评测用例${i+1}的测试目的、输出依据，并勾选核对确认。`);
  const result=await(await api('/api/validate',{programming_questions:[{...q,selected:true}]})).json();
  if(result.errors.length)throw Error(result.errors[0].error);
  if(!(state.programming_questions||[]).includes(q)||before!==JSON.stringify(programmingSnapshot(q)))throw Error('编程题已修改或移除，请重新核对');
  q.approved=true;q.approval_snapshot=programmingSnapshot(q);dirty=true;summary();renderProgramming();status('已确认此编程题，请保存进度。');
 }catch(error){q.approved=false;delete q.approval_snapshot;e.target.checked=false;status(error.message,true)}
});
$('programming-questions').addEventListener('click',async e=>{
 const card=e.target.closest('[data-programming-id]');if(!card)return;const q=state.programming_questions.find(q=>q.id===card.dataset.programmingId),d=e.target.dataset;
 if('rebuildTree' in d){
  try{const r=await(await api('/api/programming-tree-contract',{question:q,task:card.querySelector('[data-tree-task]').value})).json();Object.assign(q,r);delete q.approval_snapshot;programmingChanged(q,card);renderProgramming();status('已重建题面和8组用例。请逐组核对，平台可见性需在导入后设置。')}catch(error){status(error.message,true)}return;
 }
 if('removeContract' in d){delete q.judge_contract;programmingChanged(q,card);renderProgramming();return}
 if('removeProgramming' in d){state.programming_questions=state.programming_questions.filter(x=>x!==q);changed();summary();renderProgramming();renderQuality();renderPlan();return}
 if('addLanguage' in d){if(q.languages.length>=4){status('模板最多支持4组语言。',true);return}const language=programmingLanguages.find(l=>!q.languages.some(x=>x.language===l));q.languages.push({language,starter_code:''})}
 else if('removeLanguage' in d)q.languages.splice(+d.removeLanguage,1);
 else if('addCase' in d){if(q.test_cases.length>=1000){status('单题最多1000组用例。',true);return}q.test_cases.push({input:'',output:'',purpose:'',output_basis:'',verified:false,visibility:'hidden',excel_selected:q.test_cases.length<4})}
 else if('removeCase' in d)q.test_cases.splice(+d.removeCase,1);
 else if('addExample' in d){if((q.public_examples||[]).length>=1000){status('单题最多1000组公开样例。',true);return}(q.public_examples||=[]).push({input:'',output:''})}
 else if('removeExample' in d)q.public_examples.splice(+d.removeExample,1);
 else return;
 programmingChanged(q,card);renderProgramming();
});
function openProgramming(){ $('type-filter').value='6';$('pending-filter').checked=false;$('question-query').value='';render();$('programming-review').scrollIntoView({behavior:'smooth'}); }
$('add-programming').onclick=()=>{
 const q={id:'programming-'+crypto.randomUUID(),kind:'programming',title:'',description:'',knowledge:'',score:10,difficulty:0,time_limit_seconds:3,languages:[{language:'Python',starter_code:''}],public_examples:[],test_cases:[{input:'',output:'',purpose:'',output_basis:'',verified:false}],reference_code:'',explanation:'',source:'教师手动录入',source_refs:[],selected:true,approved:false};
 (state.programming_questions||=[]).push(q);changed();openProgramming();
};
$('upload-programming').onchange=()=>busy($('add-programming'),async()=>{
 const file=$('upload-programming').files[0];if(!file)return;if(file.size>2_000_000)throw Error('编程题文件最多2MB');
 const parsed=JSON.parse(await file.text()),items=Array.isArray(parsed)?parsed:Array.isArray(parsed.programming_questions)?parsed.programming_questions:[parsed];
 if(!items.length||items.length>100)throw Error('每次导入1–100道编程题');
 const questions=items.map(item=>({...item,test_cases:(item.test_cases||[]).map(c=>({...c,verified:false})),id:'programming-'+crypto.randomUUID(),kind:'programming',selected:true,approved:false,approval_snapshot:undefined}));
 const result=await(await api('/api/validate',{programming_questions:questions})).json();if(result.errors.length)throw Error(result.errors.map(x=>x.error).join('；'));
 (state.programming_questions||=[]).push(...questions);changed();openProgramming();$('upload-programming').value='';status(`已加载${questions.length}道编程题，请逐题核对后保存。导入文件中的审核确认不会继承。`);
});
if(state)render();

$('export-programming-tests').onclick=()=>busy($('export-programming-tests'),async()=>{
 await save();const r=await api('/api/export-programming-tests',state),url=URL.createObjectURL(await r.blob()),a=document.createElement('a');a.href=url;a.download='编程题-完整评测包.zip';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);status('已完整导出编程题评测包（教师使用）。请在平台补充全部用例并设置公开自测/内部测试；ZIP不是已验证的平台导入格式。');
});
