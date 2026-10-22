// Source readers must wait for the statement, even when navigation offers login.
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const code = fs.readFileSync(require('path').join(__dirname,'../../src/courseagent/browser/source_browser.cjs'),'utf8');
async function runFixture(loginRedirect=false) {
 let waits=0, closed=false, output='';
 const navigation='课程 导航 登录 注册 '.repeat(40);
 const statement='题目描述\n输入格式\n输出格式\n'+ '真实题面内容。'.repeat(50);
 const page={
  setDefaultTimeout(){}, async route(){}, async goto(){},
  url:()=>loginRedirect?'https://www.luogu.com.cn/auth/login':'https://www.luogu.com.cn/problem/P1001',
  async title(){return loginRedirect?'登录':'A+B Problem'},
  locator:selector=>selector==='body'?{async innerText(){return waits>=2?navigation+statement:navigation}}:
       {async allTextContents(){return waits>=2?[statement]:[]}},
  async waitForTimeout(){waits++},
  async content(){return waits>=2?'<article>'+statement+'</article>':'<nav>'+navigation+'</nav>'},
  async close(){closed=true}
 };
 const context={async newPage(){return page}};
 const browser={contexts:()=>[context],async close(){}};
 const sandbox={require:name=>name==='fs'?fs:{chromium:{async connectOverCDP(){return browser}}},
  URL,Buffer,process:{argv:['node','source_browser.cjs','--url','https://www.luogu.com.cn/problem/P1001','--cdp','http://fixture'],
   stdout:{write:value=>{output+=value}},exitCode:0}};
 await vm.runInNewContext(code,sandbox);
 assert(closed);assert.equal(sandbox.process.exitCode,0);
 return {waits,result:JSON.parse(output)};
}
(async()=>{
 const delayed=await runFixture();
 assert.equal(delayed.waits,4,'normal login link must not stop waiting for a stable statement');
 assert(delayed.result.html.includes('真实题面内容'));
 const login=await runFixture(true);
 assert.equal(login.waits,0,'an actual login redirect must stop bounded reading');
 console.log('2 source browser readiness regressions passed; no network or platform writes.');
})().catch(error=>{console.error(error);process.exitCode=1});
