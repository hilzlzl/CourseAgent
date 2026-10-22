/* Four-question delivery, field changes and server persistence. No platform writes. */
const assert=require('assert');
const {chromium}=require(process.argv[2]||'playwright');
const {verifyDraft}=require('../../src/courseagent/browser/educoder_import.cjs');
(async()=>{
 const counts=[16,18,16,14],publicCounts=[2,3,2,2];
 const coding=counts.map((count,i)=>({id:'coding-'+i,kind:'programming',title:'编程题'+i,
  description:'读取整数并输出结果。',score:10,time_limit_seconds:3,selected:true,languages:[{language:'Python'}],
  test_cases:Array.from({length:count},(_,n)=>({input:`${i}\n${n}\n`,output:`${i+n}\n`,visibility:n<publicCounts[i]?'public':'hidden'}))}));
 coding[0].description='读取整数并输出结果。\n\n```text\n1\n2\n```';
 const originalDescription=coding[0].description;
 let descriptions=coding.map(q=>q.description);
 coding[0].test_cases[15].input='9999\n'+'0\n'.repeat(5000)+'+\n'.repeat(4999);
 coding[1].test_cases[17].output='line\n'.repeat(4000);
 let stored=coding.map(q=>q.test_cases.slice(0,4).map(c=>({...c,visibility:'public'})));
 let opens=0,saves=0,fills=0,corruptSave=false;
 const changedFields=new Set();
 const browser=await chromium.launch({headless:true,...(process.platform==='win32'?{channel:'chrome'}:{})});
 try{
  const page=await browser.newPage();page.setDefaultTimeout(3000);
  await page.exposeFunction('recordFill',(i,id)=>{fills++;changedFields.add(i+':'+id)});
  await page.exposeFunction('saveCases',(i,cases,description)=>{stored[i]=cases;descriptions[i]=description;saves++;if(corruptSave)stored[i][0].output='未保存的新输出';});
  await page.route('**/*',async route=>{
   const url=new URL(route.request().url());
   if(url.pathname==='/draft')return route.fulfill({contentType:'text/html; charset=utf-8',body:
    coding.map((q,i)=>`<span class="qtitle_fixture" data-i="${i}">${q.title}</span>`).join('')+
    `<div id="detail"></div><script>document.querySelectorAll('span').forEach(e=>e.onclick=()=>{
     const d=document.querySelector('#detail');d.innerHTML=${JSON.stringify(descriptions.map(text=>text.replace(/```text\n([\s\S]*?)\n```/g,'<pre class="linenums">$1</pre>')))}[Number(e.dataset.i)];const edit=document.createElement('i');
     edit.className='icon-bianji_Hover ml8';edit.innerText='编辑';edit.onclick=()=>location.href='/editor/'+e.dataset.i;d.append(edit)});</script>`});
   if(url.pathname.startsWith('/editor/')){
    opens++;const i=Number(url.pathname.split('/').pop()),q=coding[i];
    return route.fulfill({contentType:'text/html; charset=utf-8',body:
     `<input placeholder="请输入编程题名称" value="${q.title}"><input id="f_hack_score" value="10"><input id="f_hack_time_limit" value="3">
      <input id="f_show_case" type="checkbox" checked><div id="f_hack_languages"><input type="checkbox" value="Python" checked></div>
      <div class="CodeMirror"></div><div id="cases"></div><span id="add">添加</span><button id="save">保存</button><div id="modal" hidden><span id="nocover">不覆盖</span></div>
      <script>let description=${JSON.stringify(descriptions[i])};document.querySelector('.CodeMirror').CodeMirror={getValue:()=>description,setValue:v=>description=v};function add(c={input:'',output:'',visibility:'public'}){const n=document.querySelectorAll('.ant-collapse-item').length;
       const d=document.createElement('div');d.className='ant-collapse-item';
       d.innerHTML='<div class="ant-collapse-header" aria-expanded="true"></div><textarea id="f_'+n+'_input"></textarea><textarea id="f_'+n+'_output"></textarea><input type="checkbox" id="f_'+n+'_is_public">';
       d.querySelector('[id$="_input"]').value=c.input;d.querySelector('[id$="_output"]').value=c.output;d.querySelector('input').checked=c.visibility==='public';
       d.querySelectorAll('textarea').forEach(t=>t.oninput=()=>recordFill(${i},t.id));document.querySelector('#cases').append(d)}
       ${JSON.stringify(stored[i])}.forEach(add);document.querySelector('#add').onclick=()=>add();
       document.querySelector('#save').onclick=()=>document.querySelector('#modal').hidden=false;
       document.querySelector('#nocover').onclick=async()=>{await saveCases(${i},Array.from(document.querySelectorAll('.ant-collapse-item'),d=>({
        input:d.querySelector('[id$="_input"]').value,output:d.querySelector('[id$="_output"]').value,visibility:d.querySelector('input').checked?'public':'hidden'})),description);
        location.href='/draft'};</script>`});
   }
   return route.abort();
  });
  await page.goto('https://fixture.test/draft');
  const expected={questions:[],programming_questions:coding};
  const first=await verifyDraft(page,expected);
  assert.equal(first.question_count,4);assert.equal(saves,4);assert.equal(opens,8);
  assert.equal(changedFields.size,96,'only the 48 new cases need input/output fills');
  assert([...changedFields].every(key=>Number(key.split('_')[1])>=4),'imported fields must not be rewritten');
  assert.equal(coding[0].description,originalDescription,'presentation repair must preserve the reviewed snapshot');
  assert(descriptions[0].includes('<pre class="sample-io">1\n2</pre>'),'legacy code fences must be migrated before persisted readback');
  const firstFillEvents=fills;
  assert.deepEqual(first.questions.map(q=>q.hidden_count),[14,15,14,12]);
  const second=await verifyDraft(page,expected);
  assert.equal(opens,12,'four unchanged questions need four opens total');
  assert.equal(saves,4);assert.equal(fills,firstFillEvents);assert(second.questions.every(q=>q.unchanged));
  // A server that drops a changed field must still fail persisted readback.
  coding[0].test_cases[0].output='新的期望输出';corruptSave=true;
  await assert.rejects(()=>verifyDraft(page,expected),/output不一致/);
  console.log('PASS: 4 saves, 8 initial editor opens, 4 unchanged resume opens, only 96 required fields filled; dropped server changes detected. Fixture only.');
 }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
