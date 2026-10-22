/* Playwright adapter for a teacher's own browser profile.
 * Default: inspect only. --execute imports a reviewed file into an unpublished exam.
 * Five ordinary types validated in the supplied classroom. Never clicks 发布.
 */
const fs=require('fs'),path=require('path'),crypto=require('crypto');

function args(argv){const out={};for(let i=0;i<argv.length;i++){if(argv[i].startsWith('--')){const k=argv[i].slice(2);out[k]=argv[i+1]&&!argv[i+1].startsWith('--')?argv[++i]:true}}return out}
function checkManifest(file,manifest){const bytes=fs.readFileSync(file);if(crypto.createHash('sha256').update(bytes).digest('hex')!==manifest.sha256)throw Error('导入文件与审核结果不一致，请从审核页面重新导出。');if(!Number.isInteger(manifest.question_count)||manifest.question_count<1||manifest.question_count>300)throw Error('题量超出平台限制');if(!manifest.name?.trim()||manifest.name.length>60)throw Error('试卷名称不正确');return manifest}
function validateUrl(url){const parsed=new URL(url);if(parsed.protocol!=='https:'||parsed.hostname!=='www.educoder.net'||!/^\/classrooms\/[A-Za-z0-9_-]+\/exercise(?:\/|$)/.test(parsed.pathname))throw Error('请使用头歌课堂“在线考试”页面的完整网址。');return parsed.href}
async function unique(locator,description,visibleOnly=true){const matches=visibleOnly?locator.filter({visible:true}):locator;const n=await matches.count();if(n!==1)throw Error(`${description}找到 ${n} 个位置，已停止操作，请检查页面。`);return matches}
async function selectCourse(scope,name){
 const item=scope.locator('.ant-form-item').filter({hasText:'所属课程'}).filter({visible:true});
 let box=item.locator('.ant-select-selector');
 if(await box.count()!==1)box=scope.locator('.ant-select-selector').filter({visible:true});
 if(await box.count()!==1)box=scope.getByRole('combobox');
 await (await unique(box,'所属课程')).click();
 const page=typeof scope.page==='function'?scope.page():scope;
 let option=page.getByRole('option',{name,exact:true});
 await option.or(page.locator('.ant-select-item-option-content').filter({hasText:name})).filter({visible:true}).first().waitFor();
 if(await option.filter({visible:true}).count()!==1)option=page.locator('.ant-select-item-option-content').filter({hasText:new RegExp('^'+name.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')+'$')});
 await (await unique(option,'课程选项')).click();
}
async function openCreationForm(page){
 const title=page.getByPlaceholder('请输入试卷名称',{exact:true});
 const entry=page.getByText('创建试卷',{exact:true});
 const newExam=page.getByText('创建新试卷',{exact:true});
 await title.or(entry).filter({visible:true}).first().waitFor();
 if(await title.filter({visible:true}).count())return;
 // The hover menu can briefly disappear while it is being rendered. Never
 // use a one-shot visible count to decide whether to click its item: a zero
 // count used to silently skip the click and wait for a form never opened.
 // Reopening the form is safe; only the later 下一步 submission creates it.
 for(let attempt=0;attempt<2;attempt++){
  if(await title.isVisible())return;
  try{
   await (await unique(entry,'创建试卷')).hover();
   try{await newExam.or(title).filter({visible:true}).first().waitFor({timeout:3000})}
   catch(error){if(error.name!=='TimeoutError')throw error;await (await unique(entry,'创建试卷')).click()}
   if(await title.isVisible())return;
   await newExam.filter({visible:true}).click({timeout:5000});
   await title.waitFor({timeout:8000});
   return;
  }catch(error){
   if(error.name!=='TimeoutError')throw error;
   if(attempt===1)throw Error('未能打开头歌“创建新试卷”表单；本次尚未创建或上传试卷，可重试导入。');
  }
 }
}
async function importIntoDraft(page,{file,manifest,course,job,saveJob}){
 if(!course)throw Error('需要指定平台已有的所属课程名称。');
 if(job.status==='draft_creation_started'||job.status==='upload_started'||job.status==='imported'||job.status==='saved')throw Error('上次已经开始创建或上传。请先核对平台题量，避免重复导入；本工具不会自动重试。');
 if(!job.draft_url){job.status='preparing';saveJob(job)}
 if(job.draft_url){await page.goto(job.draft_url);await page.waitForLoadState('domcontentloaded')}
 else{
  const titleInput=page.getByPlaceholder('请输入试卷名称',{exact:true});
  await titleInput.or(page.getByText('创建试卷',{exact:true})).filter({visible:true}).first().waitFor();
  if(await titleInput.filter({visible:true}).count()===0){
   // Stop on an existing same-name exam rather than creating another copy blindly.
   if(await page.getByText(manifest.name,{exact:true}).count()>0)throw Error('已存在同名试卷，请手动打开未发布试卷，并使用 --draft-url 继续。');
   await openCreationForm(page);
  }
  await page.getByPlaceholder('请输入试卷名称',{exact:true}).waitFor();
  await page.getByPlaceholder('请输入试卷名称',{exact:true}).fill(manifest.name);
  await selectCourse(page,course);
  job.status='draft_creation_started';saveJob(job);
  await (await unique(page.getByRole('button',{name:'下一步',exact:true}),'下一步')).click();
  await page.getByRole('button',{name:/Excel导入/}).waitFor();
  job.draft_url=page.url();job.status='draft_created';saveJob(job);
 }
 await page.getByRole('button',{name:/Excel导入/}).waitFor();
 await (await unique(page.getByRole('button',{name:/Excel导入/}),'Excel导入')).click();
 const modal=await unique(page.locator('.ant-modal-content'),'Excel导入弹窗');
 await selectCourse(modal,course);
 const chooser=await unique(modal.locator('input[type=file]'),'上传文件输入框',false);
 // input[type=file] may be hidden by the platform upload button.
 job.status='upload_started';saveJob(job);
 await chooser.setInputFiles(file);
 await modal.getByText(path.basename(file),{exact:true}).waitFor();
 const submit=modal.getByRole('button',{name:/^(确\s*定|确定导入|确认|导入)$/});
 await (await unique(submit,'确认导入')).click();
 await modal.waitFor({state:'hidden',timeout:60000});
 job.status='imported';job.draft_url=page.url();job.expected_questions=manifest.question_count;job.expected_score=manifest.total_score;saveJob(job);
 // Record a screenshot for human verification; this is not equivalent to answer-level readback.
 return {status:'imported_pending_verification',url:page.url(),expected_questions:manifest.question_count,expected_score:manifest.total_score};
}

function verifyQuestionDetail(detail,q){
 const normalize=s=>s.replace(/\s+/g,'');
 if(!normalize(detail).includes(normalize(q.stem)))throw Error('题干不一致');
 if(!detail.startsWith(`创建试题\n${Number(q.score).toFixed(1)}分`))throw Error('分值不一致');
 const answerSection=detail.split('\n解析')[0];let answer;
 if(q.type===1||q.type===2){
  // Source questions can include A．/B． in the stem itself. Only
  // parse the actual option block following the complete displayed stem.
  const compact=normalize(answerSection),stem=normalize(q.stem);
  const optionBlock=compact.slice(compact.indexOf(stem)+stem.length);
  const pieces=optionBlock.split(/([A-O])．/);answer='';
  const options=q.platform_options||q.options;
  if((pieces.length-1)/2!==options.length)throw Error('选项数量不一致');
  for(let k=1;k<pieces.length;k+=2){const label=pieces[k],body=pieces[k+1];const option=options[label.charCodeAt(0)-65];if(option===undefined||normalize(body.replace('正确答案',''))!==normalize(option))throw Error(`选项${label}不一致`);if(body.includes('正确答案'))answer+=label;}
  if(answer!==[...q.answer].sort().join(''))throw Error('正确答案不一致');
 }else if(q.type===3){
  const found=answerSection.match(/\n(正确|错误)\s*\n\s*正确答案/);
  answer=found&&found[1];if(answer!==q.answer)throw Error('判断题答案不一致');
 }else if(q.type===4){
  const items=[...answerSection.matchAll(/填空项(\d+)\s*\n([\s\S]*?)(?=填空项\d+|$)/g)];
  if(items.length!==q.blanks.length)throw Error('填空数量不一致');
  answer=items.map((m,i)=>{if(Number(m[1])!==i+1||normalize(m[2])!==normalize(q.blanks[i]))throw Error(`第${i+1}空答案不一致`);return q.blanks[i]});
 }else if(q.type===5){
  const found=answerSection.match(/参考答案\s*\n([\s\S]*?)判分方式/);
  if(!found||normalize(found[1])!==normalize(q.reference_answer))throw Error('参考答案不一致');
  if(!answerSection.includes('手动判分'))throw Error('简答题判分方式不一致');
  if(q.rubric&&!normalize(detail).includes(normalize(q.rubric)))throw Error('评分要点不完整');
  answer=q.reference_answer;
 }else throw Error('不支持的回读题型');
 if(q.explanation&&!normalize(detail).includes(normalize(q.explanation)))throw Error('解析不完整');
 return {id:q.id,type:q.type,answer,score:q.score,verified:true};
}
function questionPositions(labels,questions){
 const {descriptionText}=require('./educoder_programming.cjs');
 const clean=s=>descriptionText(s).replace(/^\d+[、.．]/,'').replace(/预览$/,'');
 const available=labels.map(clean),used=new Set();
 return questions.map(q=>{
  const expected=clean(q.type===7||q.kind==='programming'?q.title:q.stem);
  const matches=available.map((label,i)=>({label,i})).filter(({label,i})=>!used.has(i)&&label===expected);
  // The sidebar can append an action label, but two similar stems must never
  // silently select each other's answers. Ambiguous matches stop readback.
  if(matches.length!==1)throw Error('无法唯一定位平台题目：'+(q.title||q.stem).slice(0,100));
  used.add(matches[0].i);return matches[0].i;
 });
}
async function verifyDraft(page,expected,{configureCoding=true,onProgress=()=>{}}={}){
 const questions=expected.questions.filter(q=>q.selected);
 const coding=(expected.programming_questions||[]).filter(q=>q.selected);
 const draftUrl=page.url();
 const titles=page.locator('span[class^="qtitle_"]');await titles.first().waitFor();
 if(await titles.count()!==questions.length+coding.length)throw Error('平台题量与审核清单不一致。');
 const positions=questionPositions(await titles.allTextContents(),[...questions,...coding]);
 const results=[];
 // Configure coding questions first. A rendering mismatch while reading an
 // ordinary question must never prevent hidden judge cases from being saved
 // into the already-created draft. Each coding editor saves and reads back
 // its own public/hidden visibility before the ordinary readback starts.
 for(let i=0;i<coding.length;i++){
  const {configureAndVerify}=require('./educoder_programming.cjs');
  onProgress({stage:'coding_configuring',completed:i,total:coding.length,title:coding[i].title});
  let deadline;
  try{
   results.push(await Promise.race([
    configureAndVerify(page,coding[i],positions[questions.length+i],draftUrl,configureCoding,p=>onProgress({stage:'coding_configuring',completed:i,total:coding.length,title:coding[i].title,...p})),
    new Promise((_,reject)=>{deadline=setTimeout(()=>reject(Error('编程题配置与回读超时：'+coding[i].title)),180000);})
   ]));
  }finally{clearTimeout(deadline);}
  onProgress({stage:'coding_verified',completed:i+1,total:coding.length,title:coding[i].title,result:results[results.length-1]});
 }
 for(let i=0;i<questions.length;i++){
  await titles.nth(positions[i]).click();
  // Wait for the newly selected stem before reading the answer panel.
  await page.waitForFunction(stem=>{const t=document.body.innerText;return t.slice(t.indexOf('创建试题')).split('\n解析')[0].replace(/\s+/g,'').includes(stem)},questions[i].stem.replace(/\s+/g,''));
  // The stem can render before options/answers finish loading. Retry readback,
  // never retry upload or edit a question merely because rendering is pending.
  let readResult,lastError;
  for(let attempt=0;attempt<20;attempt++){
   const full=await page.locator('body').innerText();
   try{readResult=verifyQuestionDetail(full.slice(full.indexOf('创建试题')),questions[i]);break;}
   catch(error){lastError=error;await page.waitForTimeout(250);}
  }
  if(!readResult)throw Error(`第${i+1}题：${lastError.message}`);
  results.push(readResult);
 }
 return {question_count:questions.length+coding.length,total_score:[...questions,...coding].reduce((s,q)=>s+Number(q.score),0),questions:results};
}
const verifySingleChoiceDraft=verifyDraft;
async function saveDraft(page){
 await (await unique(page.getByText('保存试卷',{exact:true}),'保存试卷')).click();
 const modal=page.locator('.ant-modal-content').filter({visible:true});
 await Promise.race([modal.waitFor(),page.waitForURL(/\/exercise\/[^/]+\/detail/)]);
 if(!/\/exercise\/[^/]+\/detail/.test(new URL(page.url()).pathname))await (await unique(modal.getByRole('button',{name:/^保\s*存$/}),'确认保存')).click();
 await page.waitForURL(/\/exercise\/[^/]+\/detail/);
 return page.url();
}

function classifyExistingHeader(data){
 if(data?.status===-1&&data.message==='试卷不存在')return 'missing';
 if(data&&typeof data==='object'&&data.exercise_status!==undefined)return 'present';
 return 'unknown';
}
async function reconcileExisting(page,url,classroomUrl){
 const previous=validateUrl(url),course=new URL(classroomUrl).pathname.split('/')[2];
 if(new URL(previous).pathname.split('/')[2]!==course)throw Error('历史试卷不属于当前课堂');
 const id=new URL(previous).pathname.match(/\/exercise\/(\d+)\/detail/)?.[1];
 if(!id)throw Error('历史试卷网址无法核对');
 // Require the authenticated teacher classroom before accepting "not found".
 await page.goto(classroomUrl,{waitUntil:'domcontentloaded'});
 await page.getByText('创建试卷',{exact:true}).waitFor();
 const headerPromise=page.waitForResponse(r=>new URL(r.url()).pathname===`/api/exercises/${id}/common_header.json`,{timeout:20000});
 await page.goto(previous,{waitUntil:'domcontentloaded'});
 const response=await headerPromise;
 if(!response.ok())throw Error('历史试卷检查失败，未重新创建或上传');
 const data=await response.json(),status=classifyExistingHeader(data);
 if(status==='unknown')throw Error('无法确认历史试卷是否存在，未重新创建或上传');
 return {status,previous_url:previous,checked_at:new Date().toISOString(),header:data};
}

async function main(){
 const options=args(process.argv.slice(2));if(!options.url)throw Error('使用 --url 指定课堂在线考试页面；默认只查看，不创建或上传。');
 const url=validateUrl(options.url),output=options.output?path.resolve(options.output):path.join(process.cwd(),'outputs');fs.mkdirSync(output,{recursive:true});
 const {chromium}=require(options['playwright-module']||'playwright');
 const context=await chromium.launchPersistentContext(options.profile||path.join(process.cwd(),'.browser-profile'),{headless:!!options.headless,...(options.channel?{channel:options.channel}:{})});
 const page=context.pages()[0]||await context.newPage();page.setDefaultTimeout(15000);page.setDefaultNavigationTimeout(30000);
 try{
  await page.goto(url,{waitUntil:'domcontentloaded'});
  if(options['wait-login']){console.log('请在打开的浏览器中自行登录；登录后回到在线考试页面。');await page.getByText('创建试卷',{exact:true}).waitFor({timeout:300000})}
  if(!options.execute){await page.waitForTimeout(5000);await page.screenshot({path:path.join(output,'头歌页面检查.png'),fullPage:false});console.log('页面检查已保存。没有创建、上传或发布。');console.log('当前网址：'+page.url());console.log((await page.locator('body').innerText()).slice(0,1500));return}
  const file=path.resolve(options.file||path.join(output,'已审核-在线考试.xlsx'));
  const manifest=checkManifest(file,JSON.parse(fs.readFileSync(options.manifest||path.join(output,'import-manifest.json'),'utf8')));
  const jobFile=options.job?path.resolve(options.job):path.join(output,'import-job.json');
  let job=fs.existsSync(jobFile)?JSON.parse(fs.readFileSync(jobFile,'utf8')):{};
  if(job.sha256&&job.sha256!==manifest.sha256)throw Error('上一次导入任务对应其他审核文件，请保留旧任务记录后再开始新任务。');
  if(job.classroom_url&&job.classroom_url!==url)throw Error('导入任务属于另一课堂，请先核对任务记录。');
  job={...job,sha256:manifest.sha256,classroom_url:url};
  if(options['draft-url']){const draft=validateUrl(options['draft-url']);if(new URL(draft).pathname.split('/')[2]!==new URL(url).pathname.split('/')[2])throw Error('草稿不属于目标课堂');job.draft_url=draft}
  const saveJob=data=>fs.writeFileSync(jobFile,JSON.stringify(data,null,2));
  if(options['reconcile-url']){
   const reconciliation=await reconcileExisting(page,options['reconcile-url'],url);
   const {header,...record}=reconciliation;
   fs.writeFileSync(path.join(output,'reconciliation.json'),JSON.stringify(record,null,2));
   if(reconciliation.status==='present'){
    const editable=header.exercise_status===1;
    if(!editable)throw Error('历史试卷已发布或状态不允许编辑；未创建重复试卷');
    const id=new URL(options['reconcile-url']).pathname.match(/\/exercise\/(\d+)\/detail/)[1];
    await page.goto(`${url}/add/${id}?type=2`,{waitUntil:'domcontentloaded'});
    // Reconciliation must also repair and verify programming cases. A prior
    // draft can contain only public samples even when the local snapshot has
    // hidden cases, so readback-only reconciliation is insufficient.
    const verified=await verifyDraft(page,JSON.parse(fs.readFileSync(options.expected,'utf8')),{configureCoding:true});
    fs.writeFileSync(path.join(output,'import-verification.json'),JSON.stringify(verified,null,2));
    job.status='saved';job.detail_url=options['reconcile-url'];job.reconciled_at=record.checked_at;saveJob(job);
    console.log(JSON.stringify({status:'existing_verified',url:job.detail_url,verification:verified}));return;
   }
   job={sha256:manifest.sha256,classroom_url:url,status:'reconciled_missing',previous_attempt:job,reconciled_at:record.checked_at};saveJob(job);
   await page.goto(url,{waitUntil:'domcontentloaded'});
  }
  let result;
  if(options['verify-only']){
   if(!options.expected||!job.draft_url||!['imported','saved'].includes(job.status))throw Error('缺少可核对的已导入试卷，未重复上传');
   await page.goto(validateUrl(job.draft_url),{waitUntil:'domcontentloaded'});
   result={status:'imported_pending_verification',url:page.url()};
  }else result=await importIntoDraft(page,{file,manifest,course:options.course,job,saveJob});
  if(options.expected){const verified=await verifySingleChoiceDraft(page,JSON.parse(fs.readFileSync(options.expected,'utf8')),{onProgress:p=>{fs.writeFileSync(path.join(output,'coding-progress.json'),JSON.stringify(p,null,2));console.log(JSON.stringify(p));}});fs.writeFileSync(path.join(output,'import-verification.json'),JSON.stringify(verified,null,2));result.verification=verified;}
  result.url=await saveDraft(page);result.status=result.verification?'saved_verified':'saved_pending_verification';job.status='saved';job.detail_url=result.url;saveJob(job);
  await page.screenshot({path:path.join(output,'头歌导入待核对.png'),fullPage:false});
  console.log(JSON.stringify(result,null,2));console.log('请核对题量、答案、分值。试卷尚未发布。');
 }catch(error){fs.writeFileSync(path.join(output,'operation-error.json'),JSON.stringify({message:error.message,code:error.code,retryable:error.retryable,mismatches:error.mismatches,url:page.url(),at:new Date().toISOString()},null,2));await page.screenshot({path:path.join(output,'头歌操作中断.png'),fullPage:false}).catch(()=>{});throw error}
 finally{await context.close()}
}
if(require.main===module)main().catch(error=>{console.error(error.message);process.exitCode=1});
module.exports={questionPositions,classifyExistingHeader,reconcileExisting,args,checkManifest,validateUrl,openCreationForm,importIntoDraft,verifySingleChoiceDraft,verifyDraft,verifyQuestionDetail,saveDraft};
