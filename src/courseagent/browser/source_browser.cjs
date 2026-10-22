/* Read-only source tab. Never handles credentials, submits solutions or exams. */
const fs=require('fs');
const options={};for(let i=2;i<process.argv.length;i+=2)options[process.argv[i].slice(2)]=process.argv[i+1];
function allowed(url){
 try{const u=new URL(url);return u.protocol==='https:'&&!u.username&&!u.password&&(!u.port||u.port==='443')&&
 ['leetcode.cn','leetcode.com','nowcoder.com','nowcoder.net','acwing.com','luogu.com.cn','luogu.com'].some(d=>u.hostname===d||u.hostname.endsWith('.'+d));}catch{return false}
}
async function main(){
 if(!allowed(options.url))throw Error('unsupported_source');
 const {chromium}=require(options.module||'playwright');
 let browser,context,page,owned=false;
 try{
  if(options.cdp){browser=await chromium.connectOverCDP(options.cdp,{timeout:5000});context=browser.contexts()[0];}
  else{context=await chromium.launchPersistentContext(options.profile,{channel:'chrome',headless:false,timeout:8000});owned=true;}
  page=await context.newPage();page.setDefaultTimeout(4000);
  await page.route('**/*',route=>{
   const request=route.request();
   if(!['GET','HEAD'].includes(request.method())||request.isNavigationRequest()&&!allowed(request.url()))return route.abort();
   return route.continue();
  });
  await page.goto(options.url,{waitUntil:'domcontentloaded',timeout:16000});
  // Navigation text and a normal login link are not evidence that a problem
  // has loaded. Wait for statement content to settle, within the read budget.
  let previous='',stable=0;
  for(let i=0;i<24;i++){
   const text=await page.locator('body').innerText();
   const title=await page.title();
   if(/\/(?:auth\/)?(?:login|sign_in)(?:\/|$)/i.test(new URL(page.url()).pathname)||/captcha|just a moment|安全验证|access denied/i.test(title))break;
   const source=await page.locator('.problem-statement, #problem-content, .problem-content, .rendered-markdown, .markdown-body, article, main').allTextContents();
   const statement=source.join('\n')||text;
   stable=statement===previous?stable+1:0;previous=statement;
   if(statement.length>=150&&/(?:题目描述|输入格式|输入描述|输出格式|输出描述|示例\s*1|Input:|Output:|Constraints:)/i.test(statement)&&stable>=2)break;
   await page.waitForTimeout(250);
  }
  const html=await page.content();
  if(Buffer.byteLength(html)>2000000)throw Error('content_too_large');
  process.stdout.write(JSON.stringify({status:'ok',url:page.url(),html}));
 }finally{
  if(page)await page.close().catch(()=>{});
  if(owned)await context.close();else if(browser)await browser.close();
 }
}
main().catch(()=>{process.stdout.write(JSON.stringify({status:'browser_unavailable'}));process.exitCode=1});
