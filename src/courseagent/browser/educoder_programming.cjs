/* Configure all coding test sets through the teacher UI. Never publish. */
const normalize=s=>String(s).replace(/\r\n/g,'\n').trimEnd();
function nativeLiteralDelimiters(text){
 // This is a migration of our generated native prose, not a TeX sanitizer.
 return String(text).replace(/(^ {0,3}(`{3,}|~{3,})[^\n]*\n[\s\S]*?^ {0,3}\2[ \t]*$)|((`+)[^`\n]*\4)|(\\[\s\S])/gm,(value,fenced,ticks,inline,tick,escaped)=>escaped?({'(':'&#40;',')':'&#41;','[':'&#91;',']':'&#93;'}[escaped[1]]||value):value);
}
function platformDescription(q){
 const text=q.platform_description||q.description;
 return plainSampleBlocks(q.description_format==='markdown'&&q.source_refs?.some(r=>r.method==='native_structured_question')?nativeLiteralDelimiters(text):text);
}
function plainSampleBlocks(text){
 return String(text).replace(/^ {0,3}(`{3,}|~{3,})text[ \t]*\n([\s\S]*?)\n {0,3}\1[ \t]*$/gm,(_all,_fence,value)=>'<pre class="sample-io">'+value.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')+'</pre>');
}
function decodeEntities(text){
 return text.replace(/&(?:#(\d+)|#x([\da-f]+)|(amp|lt|gt|quot|apos|nbsp));/gi,(value,decimal,hex,name)=>{
  if(name)return {amp:'&',lt:'<',gt:'>',quot:'"',apos:"'",nbsp:' '}[name.toLowerCase()];
  const n=parseInt(decimal||hex,decimal?10:16);return n>0&&n<=0x10ffff?String.fromCodePoint(n):value;
 });
}
function descriptionText(value){
 // Markdown list/header markers disappear in the platform's rendered text.
 // Preserve arithmetic signs and everything inside fenced code blocks.
 let fenced=false;
 // Treat our HTML sample blocks as literal data, decoding entities once.
 const samples=[];
 const text=String(value).replace(/<pre class="sample-io">([\s\S]*?)<\/pre>/g,(_all,data)=>{samples.push(decodeEntities(data));return '\n\u0000SAMPLE'+(samples.length-1)+'\u0000\n'});
 return text.split(/\r?\n/).map(line=>{
  const sample=line.match(/^\u0000SAMPLE(\d+)\u0000$/);if(sample)return samples[Number(sample[1])];
  if(/^\s*(```|~~~)/.test(line)){fenced=!fenced;return '';}
  if(fenced)return line;
  return line.replace(/^\s{0,3}(?:[-+*]\s+|\d+[.)]\s+|#{1,6}\s+|>\s?)/,'')
   .replace(/(`+)(.*?)\1|\\([!"#$%&'()*+,\-./:;<=>?@[\\\]^_`{|}~])|&(?:#\d+|#x[\da-f]+|amp|lt|gt|quot|apos|nbsp);/gi,(match,fence,text,escaped)=>fence?text.trim():escaped||decodeEntities(match));
 }).join('\n').replace(/\s+/g,'');
}
async function verifyDescription(page,description){
 const expected=descriptionText(description);
 for(let attempt=0;attempt<20;attempt++){
  const body=await page.locator('body').innerText();
  if(body.replace(/\s+/g,'').includes(expected)){
   await verifyPlainSamples(page,description);return;
  }
  if(attempt<19)await page.waitForTimeout(250);
 }
 const blocks=await page.locator('.markdown-body').allInnerTexts();
 const actual=(blocks.find(t=>t.replace(/\s+/g,'').startsWith(expected.slice(0,12)))||'').replace(/\s+/g,'');
 let at=0;while(at<Math.min(expected.length,actual.length)&&expected[at]===actual[at])at++;
 const error=Error(`编程题题面不一致：第${at+1}个字符附近，预期${JSON.stringify(expected.slice(Math.max(0,at-25),at+65))}，实际${JSON.stringify(actual.slice(Math.max(0,at-25),at+65))}`);
 error.code='CONTENT_MISMATCH';error.retryable=false;throw error;
}
async function verifyPlainSamples(page,description){
 const expected=[...description.matchAll(/<pre class="sample-io">([\s\S]*?)<\/pre>/g)].map(m=>decodeEntities(m[1]));
 if(!expected.length)return;
 const samples=page.locator('pre.sample-io').filter({visible:true});
 const actual=await samples.evaluateAll(es=>es.map(e=>({text:e.innerText,numbered:e.classList.contains('linenums')||!!e.querySelector('ol,li')})));
 if(actual.length!==expected.length||actual.some((sample,i)=>sample.numbered||normalize(sample.text)!==normalize(expected[i]))){
  const error=Error('编程题样例展示不一致：检查样例行号、空格和换行');
  error.code='CONTENT_MISMATCH';error.retryable=false;throw error;
 }
}
async function openCase(panel){
 const header=panel.locator('.ant-collapse-header');
 const output=panel.locator('textarea[id$="_output"]');
 // Ant Collapse animates and may destroy hidden textareas. Visibility alone
 // can still be false while an already-expanded panel is mounting. Clicking
 // it again closes it and leaves the subsequent wait stuck.
 const expanded=await header.getAttribute('aria-expanded');
 if(expanded==='false'||expanded===null&&!(await output.isVisible())){
  await header.click({position:{x:60,y:12}});
 }
 await output.waitFor({state:'visible'});
}
async function writeCaseText(field,value){
 if(value.length>=8192||value.split('\n').length>=1000){
  await field.waitFor({state:'visible'});
  // Chromium's editing command can stall on thousands of lines. Use the
  // textarea setter and a bubbling input event so React receives the full value.
  await field.evaluate((element,text)=>{
   if(element.disabled||element.readOnly)throw Error('评测用例输入框不可编辑');
   Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set.call(element,text);
   element.dispatchEvent(new Event('input',{bubbles:true}));
  },value);
 }else await field.fill(value);
 if(normalize(await field.inputValue())!==normalize(value))throw Error('评测用例文字写入后回读不一致');
}
async function readEditorCases(page){
 const panels=page.locator('.ant-collapse-item');const result=[];
 for(let i=0;i<await panels.count();i++){
  const panel=panels.nth(i);
  await openCase(panel);
  const input=panel.locator('textarea[id$="_input"]'),output=panel.locator('textarea[id$="_output"]');
  await output.waitFor();
  result.push({input:await input.inputValue(),output:await output.inputValue(),visibility:await panel.locator('input[id$="_is_public"]').isChecked()?'public':'hidden'});
 }
 return result;
}
function persistedEditorData(data,q,verifySettings=false){
 // Unknown/incomplete schemas use the UI fallback. Recognized mismatches
 // must still reach verifyCases; never hide a server defect with local data.
 if(!data||typeof data.name!=='string'||!Array.isArray(data.hack_sets)||
    !Array.isArray(data.languages)||!data.languages.every(x=>typeof x==='string')||
    typeof data.show_case!=='boolean'||typeof data.time_limit!=='number'||
    data.hack_sets.some((c,i)=>!c||typeof c.input!=='string'||typeof c.output!=='string'||
     typeof c.is_public!=='boolean'||!Number.isInteger(c.position)||c.position!==i+1||
     !Number.isInteger(c.id)||c.is_file!==false)||
    new Set(data.hack_sets.map(c=>c.id)).size!==data.hack_sets.length)return null;
 if(data.name!==q.title)throw Error('服务器返回的编程题题名不一致');
 if(verifySettings&&data.time_limit!==q.time_limit_seconds)throw Error('服务器返回的评测时限不一致');
 const languages=q.languages.map(l=>l.language==='C语言'?'C':l.language).sort();
 if(verifySettings&&JSON.stringify(data.languages.slice().sort())!==JSON.stringify(languages))throw Error('服务器返回的编程题允许语言不一致');
 if(verifySettings&&!data.show_case)throw Error('公开用例的评测可见性未保存');
 return {cases:data.hack_sets.map(c=>({input:c.input,output:c.output,visibility:c.is_public?'public':'hidden'})),
  case_ids:data.hack_sets.map(c=>c.id),method:'server_response'};
}
async function openEditorReadback(page,q,verifySettings=false){
 // Observe only the request caused by THIS editor navigation. Do not issue
 // additional API calls or reuse a response from before a save.
 const responses=[];
 const observe=response=>{
  const url=new URL(response.url());
  if(response.request().method()==='GET'&&/^\/api\/problems\/[^/]+\/edit\.json$/.test(url.pathname))
   responses.push({url,payload:response.ok()?response.json().catch(()=>null):Promise.resolve(null)});
 };
 page.on('response',observe);
 try{
  await page.locator('i.icon-bianji_Hover.ml8').filter({visible:true}).click();
  await page.getByPlaceholder('请输入编程题名称',{exact:true}).waitFor();
  const editor=new URL(page.url()),slug=editor.pathname.match(/^\/problems\/newedit\/([^/]+)$/)?.[1];
  const matching=responses.filter(r=>r.url.protocol===editor.protocol&&
   (r.url.hostname===editor.hostname||editor.hostname==='www.educoder.net'&&r.url.hostname==='data.educoder.net')&&
   r.url.pathname===`/api/problems/${slug}/edit.json`);
  if(!slug||matching.length!==1)return null;
  return persistedEditorData(await matching[0].payload,q,verifySettings);
 }finally{page.off('response',observe)}
}
function verifyCases(actual,expected){
 if(actual.length!==expected.length)throw Error('编程用例数量不一致');
 actual.forEach((c,i)=>{for(const k of ['input','output'])if(normalize(c[k])!==normalize(expected[i][k]))throw Error(`编程用例${i+1}的${k}不一致：实际${JSON.stringify(c[k]).slice(0,160)}，预期${JSON.stringify(expected[i][k]).slice(0,160)}`);
 });
 // Check ALL content first: only a pure visibility mismatch may be repaired
 // automatically after persistence, never a content/order mismatch.
 const mismatches=actual.flatMap((c,i)=>c.visibility===(expected[i].visibility||'hidden')?[]:[{case_index:i+1,expected:expected[i].visibility||'hidden',actual:c.visibility}]);
 if(mismatches.length){
  const error=Error(`编程用例${mismatches[0].case_index}公开状态不一致：预期${mismatches[0].expected}，实际${mismatches[0].actual}`);
  error.code='CASE_VISIBILITY_MISMATCH';error.mismatches=mismatches;throw error;
 }
 return {case_count:actual.length,public_count:actual.filter(c=>c.visibility==='public').length,hidden_count:actual.filter(c=>c.visibility==='hidden').length,verified:true};
}
async function verifyLanguages(page,q){
 const actual=await page.locator('[id$="_hack_languages"] input:checked').evaluateAll(es=>es.map(e=>e.value).sort());
 const expected=q.languages.map(l=>l.language==='C语言'?'C':l.language).sort();
 if(JSON.stringify(actual)!==JSON.stringify(expected))throw Error('编程题允许语言不一致');
 return actual;
}
async function readInitialCode(page){
 const input=page.locator('.monaco-editor[role="code"] textarea.inputarea');
 await input.press('Control+a');
 // Use the editor's copy event without touching the system clipboard.
 return input.evaluate(e=>{const data=new DataTransfer();e.dispatchEvent(new ClipboardEvent('copy',{bubbles:true,cancelable:true,clipboardData:data}));return data.getData('text/plain')});
}
async function syncInitialCode(page,q,write=false){
 if(!q.io_contract)return {checked:false,changed:false};
 let changed=false;const languages=[];
 await page.getByText('学员初始代码',{exact:true}).click();
 try{
  for(const item of q.languages){
   const name=item.language==='C语言'?'C':item.language;
   const tab=page.locator('aside').filter({has:page.getByText(name,{exact:true})});
   await tab.click();
   await page.waitForFunction(name=>[...document.querySelectorAll('aside')].some(e=>e.textContent.trim()===name&&/active/.test(e.className)),name);
   await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
   if(normalize(await readInitialCode(page))!==normalize(item.starter_code)){
    if(!write)throw Error('编程题初始代码与交付内容不一致：'+name);
    if(!item.starter_code)await page.locator('.monaco-editor[role="code"] textarea.inputarea').press('Backspace');
    else await page.locator('.monaco-editor[role="code"] textarea.inputarea').evaluate((e,text)=>{
     const data=new DataTransfer();data.setData('text/plain',text);
     e.dispatchEvent(new ClipboardEvent('paste',{bubbles:true,cancelable:true,clipboardData:data}));
    },item.starter_code);
    await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(resolve)));
    const actual=await readInitialCode(page);
    if(normalize(actual)!==normalize(item.starter_code)){
     let at=0;while(at<Math.min(actual.length,item.starter_code.length)&&actual[at]===item.starter_code[at])at++;
     throw Error('编程题初始代码写入后回读不一致：'+name+'，位置'+at+'，实际'+JSON.stringify(actual.slice(Math.max(0,at-30),at+100)));
    }
    changed=true;
   }
   languages.push(name);
  }
 }finally{await page.getByText('题目设置',{exact:true}).click()}
 return {checked:true,changed,languages};
}
function bulkFiles(cases,start=0){
 return cases.flatMap((c,i)=>['input','output'].map((key,k)=>{
  if(typeof c[key]!=='string')throw Error('评测文件内容必须是文本');
  const buffer=Buffer.from(c[key],'utf8');
  if(buffer.length>100*1024*1024)throw Error('单个评测文件超过网站100MB限制');
  return {name:`case-${String(start+i+1).padStart(4,'0')}.${k?'out':'in'}`,mimeType:'text/plain',buffer};
 }));
}
async function appendBulkCases(page,cases,start,onProgress=()=>{}){
 const button=page.getByRole('button',{name:'批量上传',exact:true});
 if(cases.length<4||await button.count()!==1)return false;
 for(let offset=0;offset<cases.length;offset+=20){
  const batch=cases.slice(offset,offset+20),files=bulkFiles(batch,start+offset);
  await button.click();
  const modal=page.locator('.ant-modal-content').filter({visible:true});
  await modal.waitFor();
  const fileInput=modal.locator('input[type="file"]');
  if(await fileInput.count()!==1)throw Error('批量上传窗口结构已变化');
  await fileInput.setInputFiles(files);
  // The site pairs by basename and preserves the first occurrence of each
  // basename. Supply in/out consecutively, then verify every filename before
  // committing this unsaved editor change.
  for(const file of files)await modal.getByText(file.name,{exact:true}).first().waitFor();
  onProgress({step:'bulk_uploading_cases',case_count:start+offset,case_total:start+cases.length});
  await modal.getByRole('button',{name:'确认',exact:true}).click();
  const expected=start+offset+batch.length;
  await page.waitForFunction(n=>document.querySelectorAll('.ant-collapse-item').length===n,expected);
  await modal.waitFor({state:'hidden'});
 }
 return true;
}
async function configureEditor(page,q,onProgress=()=>{},forceSave=false,persisted=null){
 await page.getByPlaceholder('请输入编程题名称',{exact:true}).waitFor();
 if(await page.getByPlaceholder('请输入编程题名称',{exact:true}).inputValue()!==q.title)throw Error('当前编程编辑器题名不匹配');
 const expected=q.languages.map(l=>l.language==='C语言'?'C':l.language);
 const languageInputs=page.locator('[id$="_hack_languages"] input');
 const beforeLanguages=await languageInputs.evaluateAll(es=>es.filter(e=>e.checked).map(e=>e.value).sort());
 const languageChanged=JSON.stringify(beforeLanguages)!==JSON.stringify(expected.map(x=>x==='C语言'?'C':x).sort());
 const score=Number(await page.locator('input[id$="_hack_score"]').inputValue());
 if(score!==Number(q.score))throw Error('编程题分值不一致');
 if(Number(await page.locator('input[id$="_hack_time_limit"]').inputValue())!==q.time_limit_seconds)throw Error('编程题评测时限不一致');
 for(let i=0;i<await languageInputs.count();i++){
  const input=languageInputs.nth(i),checked=expected.includes(await input.getAttribute('value'));
  if(await input.isChecked()!==checked)await input.setChecked(checked);
 }
 await verifyLanguages(page,q);
 const templates=await syncInitialCode(page,q,true);
 const panels=page.locator('.ant-collapse-item');
 if(await panels.count()>q.test_cases.length)throw Error('平台已有多余用例，停止以避免误删');
 // Resuming a partially completed import must be idempotent. If the draft
 // already contains exactly the requested cases and visibility, read them
 // back and skip the save dialog entirely. Only changed fields continue to
 // the write path below.
 if(await panels.count()===q.test_cases.length){
  try{
   const existing=verifyCases(persisted?persisted.cases:await readEditorCases(page),q.test_cases);
   const showCase=page.locator('input[id$="_show_case"]');
   if(!forceSave && !languageChanged && !templates.changed && await showCase.count()===1 && await showCase.isChecked()){
    onProgress({step:'cases_already_synced',case_count:existing.case_count,public_count:existing.public_count,hidden_count:existing.hidden_count});
    return {...existing,case_readback_method:persisted?'server_response':'editor_ui',initial_code_verified:templates.checked,unchanged:true};
   }
  }catch(_error){/* incomplete or stale editor; continue with repair */}
 }
 const initialCount=await panels.count();
 const bulkUsed=await appendBulkCases(page,q.test_cases.slice(initialCount),initialCount,onProgress);
 while(await panels.count()<q.test_cases.length){
  const before=await panels.count();onProgress({step:'adding_cases',case_count:before,case_total:q.test_cases.length});await page.getByText('添加',{exact:true}).click();
  await page.waitForTimeout(150);
  await page.waitForFunction(n=>document.querySelectorAll('.ant-collapse-item').length>n,before);
 }
 const actualCases=[];
 for(let i=0;i<q.test_cases.length;i++){
  const panel=panels.nth(i);
  // Imported cases are already populated by the site's parser. Their
  // visibility controls are in the header, so no accordion cycle is needed.
  // Content is authoritatively checked after save/reload by configureAndVerify.
  if(bulkUsed&&i>=initialCount){
   const visibility=panel.locator('input[id$="_is_public"]');
   const checked=q.test_cases[i].visibility==='public';
   // The bulk dialog leaves is_public undefined in Ant Form, although the
   // checkbox looks unchecked. An untouched field is omitted from the POST
   // and the server defaults it to PUBLIC. Force a real change event even
   // when the visual value already matches; keep the accordion collapsed.
   if(await visibility.isChecked()===checked)await visibility.setChecked(!checked);
   await visibility.setChecked(checked);
   continue;
  }
  await openCase(panel);
  const input=panel.locator('textarea[id$="_input"]'),output=panel.locator('textarea[id$="_output"]');
  const visibility=panel.locator('input[id$="_is_public"]');
  const changed=[];
  for(const [name,field] of [['input',input],['output',output]]){
   if(normalize(await field.inputValue())!==normalize(q.test_cases[i][name])){
    await writeCaseText(field,q.test_cases[i][name]);changed.push(name);
   }
  }
  if(await visibility.isChecked()!==(q.test_cases[i].visibility==='public')){
   await visibility.setChecked(q.test_cases[i].visibility==='public');changed.push('visibility');
  }
  actualCases.push({input:await input.inputValue(),output:await output.inputValue(),
   visibility:await visibility.isChecked()?'public':'hidden'});
  onProgress({step:changed.length?'writing_case':'case_unchanged',case_index:i+1,case_total:q.test_cases.length,changed_fields:changed});
 }
 // Public tests may be shown on failed evaluations; hidden inputs stay hidden.
 const showCase=page.locator('input[id$="_show_case"]');
 if(!(await showCase.isChecked()))await showCase.setChecked(true);
 // Each edited panel was read back above. Reopening the entire accordion
 // here only repeats that local check and visibly cycles every test again.
 // configureAndVerify still reloads and reads every server-persisted case.
 const result=bulkUsed?{case_count:await panels.count(),
  public_count:await page.locator('.ant-collapse-header input[id$="_is_public"]:checked').count(),
  hidden_count:q.test_cases.filter(c=>c.visibility!=='public').length,
  pre_save_content_check:'deferred_to_persisted_readback',bulk_uploaded:true}:verifyCases(actualCases,q.test_cases);
 onProgress({step:'saving_cases'});
 await page.getByRole('button',{name:'保存',exact:true}).click();
 const noOverwrite=page.getByText('不覆盖',{exact:true}).filter({visible:true});
 await noOverwrite.waitFor({timeout:15000});
 await noOverwrite.click();
 await noOverwrite.waitFor({state:'hidden'});
 return {...result,initial_code_verified:templates.checked};
}
async function configureAndVerify(page,q,index,draftUrl,configure=true,onProgress=()=>{}){
 const title=page.locator('span[class^="qtitle_"]').nth(index);
 if(!(await title.innerText()).includes(q.title))throw Error('平台编程题顺序或题名不一致');
 await title.click();
 // A deterministic statement defect cannot be repaired by rewriting cases.
 onProgress({step:'checking_description'});
 const description=platformDescription(q),original=q.platform_description||q.description;
 let editorOpen=false,descriptionRepaired=false,persisted=null;
 try{await verifyDescription(page,description)}catch(error){
  // A narrowly scoped recovery for our legacy escaped literal delimiters.
  // Confirm the persisted raw text still exactly matches the frozen snapshot
  // before changing it. Any other statement defect remains a hard failure.
  if(!configure||error.code!=='CONTENT_MISMATCH'||description===original||descriptionText(description)!==descriptionText(original))throw error;
  await page.locator('i.icon-bianji_Hover.ml8').filter({visible:true}).click();
  await page.getByPlaceholder('请输入编程题名称',{exact:true}).waitFor();
  const repaired=await page.locator('.CodeMirror').evaluateAll((editors,{original,description})=>{
   const matches=editors.filter(e=>e.CodeMirror?.getValue()===original);
   if(matches.length!==1)return false;
   matches[0].CodeMirror.setValue(description);return true;
  },{original,description});
  if(!repaired)throw error;
  editorOpen=true;descriptionRepaired=true;onProgress({step:'repairing_literal_delimiters'});
 }
 if(configure){
  if(!editorOpen)persisted=await openEditorReadback(page,q);
  await page.getByPlaceholder('请输入编程题名称',{exact:true}).waitFor();
  // Presentation-only upgrades preserve the frozen assessment and its data.
  // Replace only our exact original representation, never arbitrary edits.
  if(description!==original){
   const raw=await page.locator('.CodeMirror').first().evaluate(e=>e.CodeMirror.getValue());
   if(raw!==description){
    if(raw!==original&&raw!==nativeLiteralDelimiters(original))throw Error('平台编程题原始题面已被修改，停止自动调整样例格式');
    await page.locator('.CodeMirror').first().evaluate((e,text)=>e.CodeMirror.setValue(text),description);
    descriptionRepaired=true;onProgress({step:'formatting_plain_samples'});
   }
  }
  const configured=await configureEditor(page,q,onProgress,descriptionRepaired,persisted);
  // This editor was freshly loaded from the server. With no mutations its
  // verified values already prove persistence; a second open adds no evidence.
  if(configured.unchanged){
   const languages=await verifyLanguages(page,q);
   onProgress({step:'persisted_cases_already_verified'});
   await page.goto(draftUrl,{waitUntil:'domcontentloaded'});
   await page.locator('span[class^="qtitle_"]').first().waitFor();
   return {id:q.id,type:7,score:q.score,languages,time_limit_seconds:q.time_limit_seconds,...configured};
  }
  await page.waitForURL(draftUrl,{timeout:30000});
 }
 // Reload to prove server persistence, rather than checking unsaved form values.
 // A pure visibility defect is safe to correct once in this same draft.
 // Content, question identity, language or score mismatches still stop here.
 for(let attempt=0;attempt<2;attempt++){
  onProgress({step:'reading_persisted_cases'});
  await page.reload({waitUntil:'domcontentloaded'});
  await page.locator('span[class^="qtitle_"]').nth(index).click();
  await page.waitForFunction(t=>document.body.innerText.includes(t),q.title);
  await verifyDescription(page,description);
  // The exam's display table flattens multi-line input. Read persisted
  // textareas instead so line boundaries are checked exactly.
  const persisted=await openEditorReadback(page,q,true);
  await page.getByPlaceholder('请输入编程题名称',{exact:true}).waitFor();
  if(await page.getByPlaceholder('请输入编程题名称',{exact:true}).inputValue()!==q.title)throw Error('保存后的题名不一致');
  if(Number(await page.locator('input[id$="_hack_score"]').inputValue())!==Number(q.score))throw Error('保存后的分值不一致');
  if(Number(await page.locator('input[id$="_hack_time_limit"]').inputValue())!==q.time_limit_seconds)throw Error('保存后的评测时限不一致');
  const languages=await verifyLanguages(page,q);
  const actualCases=persisted?persisted.cases:await readEditorCases(page);
  let cases;
  try{cases=verifyCases(actualCases,q.test_cases)}catch(error){
   if(error.code!=='CASE_VISIBILITY_MISMATCH')throw error;
   if(!configure||attempt===1){error.retryable=false;throw error;}
   await syncInitialCode(page,q,false);
   onProgress({step:'repairing_persisted_visibility',attempt:1,mismatches:error.mismatches});
   await configureEditor(page,q,onProgress);
   await page.waitForURL(draftUrl,{timeout:30000});
   continue;
  }
  if(!(await page.locator('input[id$="_show_case"]').isChecked()))throw Error('公开用例的评测可见性未保存');
  const templates=await syncInitialCode(page,q,false);
  await page.goto(draftUrl,{waitUntil:'domcontentloaded'});
  await page.locator('span[class^="qtitle_"]').first().waitFor();
  return {id:q.id,type:7,score:q.score,languages,time_limit_seconds:q.time_limit_seconds,...cases,
   case_readback_method:persisted?'server_response':'editor_ui',persisted_case_ids:persisted?.case_ids,initial_code_verified:templates.checked};
 }
}
module.exports={nativeLiteralDelimiters,plainSampleBlocks,platformDescription,descriptionText,verifyDescription,verifyPlainSamples,openCase,writeCaseText,readEditorCases,persistedEditorData,openEditorReadback,verifyCases,verifyLanguages,readInitialCode,syncInitialCode,bulkFiles,appendBulkCases,configureEditor,configureAndVerify};
