/* Exercise the real navigation/response path with collapsed, unmounted cases. */
const assert=require('assert');
const {chromium}=require(process.argv[2]||'playwright');
const {configureAndVerify,persistedEditorData,verifyCases}=require('../../src/courseagent/browser/educoder_programming.cjs');
(async()=>{
 const q={id:'coding',title:'队列轮转',description:'读取队列并输出结果。',score:10,time_limit_seconds:3,
  languages:[{language:'Python'}],test_cases:[{input:'1\n2\n',output:'2\n',visibility:'public'},
   {input:'3\n4\n',output:'4\n',visibility:'hidden'}]};
 const base={name:q.title,languages:['Python'],show_case:true,time_limit:3,
  hack_sets:q.test_cases.map((c,i)=>({id:i+1,position:i+1,is_file:false,input:c.input,output:c.output,is_public:c.visibility==='public'}))};
 assert.equal(persistedEditorData({...base,hack_sets:[{...base.hack_sets[0],is_public:undefined}]},q),null);
 assert.equal(persistedEditorData({...base,hack_sets:[{...base.hack_sets[0],is_public:'false'}]},q),null);
 assert.equal(persistedEditorData({...base,hack_sets:[{...base.hack_sets[0],is_file:true}]},q),null);
 assert.throws(()=>persistedEditorData({...base,name:'另一道同数量题'},q),/题名不一致/);
 assert.throws(()=>persistedEditorData({...base,languages:['C']},q,true),/语言不一致/);
 assert.throws(()=>verifyCases(persistedEditorData({...base,hack_sets:[]},q).cases,q.test_cases),/数量不一致/);
 const browser=await chromium.launch({headless:true,...(process.platform==='win32'?{channel:'chrome'}:{})});
 try{
  const page=await browser.newPage();page.setDefaultTimeout(2000);
  const draft='https://fixture.test/draft';let expands=0,mode='normal';
  await page.exposeFunction('caseExpanded',()=>{expands++});
  await page.route('**/*',async route=>{
   const url=new URL(route.request().url());
   if(url.pathname==='/api/problems/code1/edit.json'){
    const data=JSON.parse(JSON.stringify(base));
    if(mode==='unknown')delete data.hack_sets[0].position;
    if(mode==='corrupt')data.hack_sets[1].output='服务器实际保存错了';
    return route.fulfill({json:data});
   }
   if(url.pathname==='/draft')return route.fulfill({contentType:'text/html; charset=utf-8',body:
    `<span class="qtitle_fixture">${q.title}</span><div id="detail"></div><script>
     document.querySelector('span').onclick=()=>{document.querySelector('#detail').innerHTML=${JSON.stringify(q.description+'<i class="icon-bianji_Hover ml8">编辑</i>')};document.querySelector('i').onclick=()=>location.href='/problems/newedit/code1'};
     </script>`});
   if(url.pathname==='/problems/newedit/code1')return route.fulfill({contentType:'text/html; charset=utf-8',body:
    `<main></main><script>fetch('/api/problems/code1/edit.json').then(r=>r.json()).then(data=>{
     document.querySelector('main').innerHTML='<input placeholder="请输入编程题名称"><input id="f_hack_score" value="10"><input id="f_hack_time_limit" value="3"><input id="f_show_case" type="checkbox" checked><div id="f_hack_languages"><input type="checkbox" value="Python" checked></div><div id="cases"></div>';
     document.querySelector('[placeholder]').value=data.name;
     data.hack_sets.forEach((c,i)=>{const p=document.createElement('div');p.className='ant-collapse-item';p.innerHTML='<div class="ant-collapse-header" aria-expanded="false">展开</div><div class="fields"></div>';p.querySelector('.ant-collapse-header').onclick=()=>{
      caseExpanded();p.querySelector('.ant-collapse-header').setAttribute('aria-expanded','true');p.querySelector('.fields').innerHTML='<textarea id="f_'+i+'_input"></textarea><textarea id="f_'+i+'_output"></textarea><input id="f_'+i+'_is_public" type="checkbox">';
      p.querySelector('textarea[id$="_input"]').value=c.input;p.querySelector('textarea[id$="_output"]').value=c.output;p.querySelector('input').checked=c.is_public;
     };document.querySelector('#cases').append(p)});
    });</script>`});
   return route.abort();
  });
  await page.goto(draft);let result=await configureAndVerify(page,q,0,draft,false);
  assert.equal(result.case_readback_method,'server_response');assert.equal(result.hidden_count,1);assert.equal(expands,0);
  // Unchanged resumption also consumes the newly loaded server response.
  result=await configureAndVerify(page,q,0,draft,true);
  assert(result.unchanged);assert.equal(result.case_readback_method,'server_response');assert.equal(expands,0);
  mode='unknown';result=await configureAndVerify(page,q,0,draft,false);
  assert.equal(result.case_readback_method,'editor_ui');assert.equal(expands,2,'unknown schema must fall back to full UI readback');
  mode='corrupt';await assert.rejects(()=>configureAndVerify(page,q,0,draft,false),/output不一致/);
  console.log('PASS: persisted network response, no accordion opens, unchanged resume, schema fallback and corrupted server output detected. Fixture only.');
 }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
