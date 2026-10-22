/* Full browser fixture: save -> persisted readback -> unchanged resume.
 * No network or Educoder writes; catches navigation regressions between helpers.
 */
const assert=require('assert');
const {chromium}=require(process.argv[2]||'playwright');
const {verifyDraft,questionPositions}=require('../../src/courseagent/browser/educoder_import.cjs');
(async()=>{
 const q={id:'coding',kind:'programming',title:'队列求和',description:'读取整数并输出结果。',score:10,time_limit_seconds:3,languages:[{language:'Python'}],selected:true,
 test_cases:[{input:'1\n',output:'1\n',visibility:'public'},{input:'-7\n',output:'-7\n',visibility:'hidden'}]};
 const judge={id:'judge',type:3,stem:'栈遵循后进先出。',answer:'正确',score:10,selected:true};
 const choice={id:'choice',type:1,stem:'哪个结构先进先出？',options:['队列','栈'],answer:'A',score:10,selected:true};
 const expected={questions:[judge,choice],programming_questions:[q]};
 assert.deepEqual(questionPositions(['1、 哪个结构先进先出？ 预览','2、 栈遵循后进先出。 预览','3、 队列求和 预览'],[judge,choice,q]),[1,0,2]);
 assert.throws(()=>questionPositions(['1、 同题 预览','2、 同题 预览'],[{stem:'同题',type:3}]),/唯一定位/);
 const browser=await chromium.launch({headless:true,...(process.platform==='win32'?{channel:'chrome'}:{})});
 try{
  const page=await browser.newPage();page.setDefaultTimeout(2000);
  const url='https://fixture.test/draft';let saves=0,opens=0,corruptSaves=1;
  let stored=q.test_cases.map(c=>({...c,visibility:'public'}));
  await page.exposeFunction('fixtureSave',cases=>{stored=cases.map(c=>({...c,visibility:corruptSaves>0?'public':c.visibility}));corruptSaves--;saves++});
  await page.route('**/*',async route=>{
   if(route.request().url()===url){
    return route.fulfill({contentType:'text/html; charset=utf-8',body:`<span class="qtitle_fixture" data-id="choice">1、 ${choice.stem} 预览</span><span class="qtitle_fixture" data-id="judge">2、 ${judge.stem} 预览</span><span class="qtitle_fixture" data-id="coding">3、 ${q.title} 预览</span><div id="detail"></div><script>
    const rows=${JSON.stringify({choice:`创建试题\n10.0分\n${choice.stem}\nA．队列\n正确答案\nB．栈`,judge:`创建试题\n10.0分\n${judge.stem}\n正确\n正确答案`,coding:q.description})};
    document.querySelectorAll('span').forEach(e=>e.onclick=()=>{const d=document.querySelector('#detail');d.innerText=rows[e.dataset.id];if(e.dataset.id==='coding'){const i=document.createElement('i');i.className='icon-bianji_Hover ml8';i.innerText='编辑';i.onclick=()=>location.href='/editor';d.append(i)}});
    </script>`});
   }
   if(route.request().url()==='https://fixture.test/editor'){
    opens++;
    return route.fulfill({contentType:'text/html; charset=utf-8',body:`<input placeholder="请输入编程题名称" value="${q.title}"><input id="f_hack_score" value="10"><input id="f_hack_time_limit" value="3"><input type="checkbox" id="f_show_case" checked><div id="f_hack_languages"><input type="checkbox" value="Python" checked></div><div id="cases"></div><button id="save">保存</button><div id="modal" hidden><span id="nocover">不覆盖</span></div><script>
    const cases=${JSON.stringify(stored)};
    cases.forEach((c,n)=>{const d=document.createElement('div');d.className='ant-collapse-item';d.innerHTML='<div class="ant-collapse-header"><span class="ant-collapse-expand-icon">展开</span></div><textarea id="f_'+n+'_input"></textarea><textarea id="f_'+n+'_output"></textarea><input type="checkbox" id="f_'+n+'_is_public">';document.querySelector('#cases').append(d);d.querySelector('[id$="_input"]').value=c.input;d.querySelector('[id$="_output"]').value=c.output;d.querySelector('input').checked=c.visibility==='public'});
    document.querySelector('#save').onclick=()=>document.querySelector('#modal').hidden=false;
    document.querySelector('#nocover').onclick=async()=>{await fixtureSave(Array.from(document.querySelectorAll('.ant-collapse-item'),d=>({input:d.querySelector('[id$="_input"]').value,output:d.querySelector('[id$="_output"]').value,visibility:d.querySelector('input').checked?'public':'hidden'})));location.href='/draft'};
    </script>`});
   }
   return route.abort();
  });
  await page.goto(url);const first=await verifyDraft(page,expected);
  assert.equal(first.question_count,3);assert.equal(saves,2,'a visibility-only persistence failure is repaired once');assert.equal(stored[1].visibility,'hidden');
  const second=await verifyDraft(page,expected);
  assert.equal(second.questions[0].hidden_count,1);assert.equal(saves,2,'unchanged resume must not save again');
  assert.equal(opens,4,'initial save, failed readback and repaired readback, then unchanged resume');
  assert.equal(page.url(),url);
  corruptSaves=100;stored[1].visibility='public';const before=saves;
  await assert.rejects(()=>verifyDraft(page,expected),e=>e.code==='CASE_VISIBILITY_MISMATCH'&&e.retryable===false);
  assert.equal(saves-before,2,'persistent mismatch stops after one local repair, never loops');
  await page.goto(url);const noWrite=saves;
  await assert.rejects(()=>verifyDraft(page,expected,{configureCoding:false}),e=>e.code==='CASE_VISIBILITY_MISMATCH');
  assert.equal(saves,noWrite,'read-only verification must never repair');
  console.log('PASS: grouped ordinary questions; hidden-case repair persisted; unchanged resume navigates and reads back without duplicate save. Fixture only.');
 }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
