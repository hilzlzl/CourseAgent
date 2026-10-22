// Exercise the real frontend with synthetic local responses, without models or platform writes.
const assert = require('assert');
const fs = require('fs');
const http = require('http');
const path = require('path');
const {chromium} = require(process.argv[2] || 'playwright');
const web = path.join(__dirname, '../../src/courseagent/web');
const saved = {id:'saved-fixture', status:'ready', request:'历史作业：栈与队列', files:[]};
let tasks = [saved], submissions = [];
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://localhost');
  if (req.method === 'POST' && url.pathname === '/api/agent-start') {
    let text = '';
    for await (const chunk of req) text += chunk;
    const payload = JSON.parse(text);
    submissions.push(payload);
    const task = {id:'new-fixture', status:'ready', request:payload.prompt, files:[]};
    tasks = [task, saved];
    res.setHeader('Content-Type', 'application/json');
    return res.end(JSON.stringify(task));
  }
  const responses = {
    '/api/review':{name:'空白作业', version:0, questions:[], programming_questions:[]},
    '/api/sources':{sources:[], errors:[]},
    '/api/agent-tasks':{tasks},
    '/api/model-status':{configured:false},
    '/api/workflow':{nodes:[], edges:[], engine:'fixture', model_mode:'offline'},
    '/api/import-jobs':{jobs:[]},
    '/api/review-tasks':{tasks:[]},
    '/api/observability':{enabled:false}
  };
  if (url.pathname in responses) {
    res.setHeader('Content-Type', 'application/json');
    return res.end(JSON.stringify(responses[url.pathname]));
  }
  if (url.pathname === '/api/agent-events') {
    res.setHeader('Content-Type', 'text/event-stream');
    return res.end(': fixture\n\n');
  }
  const files = {'/':'index.html', '/styles.css':'styles.css', '/app.js':'app.js', '/agent_ui.js':'agent_ui.js', '/programming_review.js':'programming_review.js', '/workspace.js':'workspace.js'};
  const file = files[url.pathname];
  if (!file) {res.statusCode = 404; return res.end();}
  res.setHeader('Content-Type', file.endsWith('.css') ? 'text/css' : file.endsWith('.js') ? 'text/javascript' : 'text/html; charset=utf-8');
  res.end(fs.readFileSync(path.join(web, file)));
});

(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({headless:true});
  try {
    const page = await browser.newPage({viewport:{width:1440, height:1000}});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const address = `http://127.0.0.1:${server.address().port}`;
    await page.goto(address);
    await page.waitForFunction(() => !document.querySelector('#attach-material').disabled && document.querySelector('#history-count').textContent === '1');
    assert.equal(await page.locator('#agent-prompt').inputValue(), '');
    assert.equal(await page.locator('#agent-tasks').innerText(), '', 'saved tasks must not become the current task');
    await page.getByRole('button', {name:'开始生成作业', exact:true}).click();
    assert.equal(submissions.length, 0, 'empty prompts must not submit');
    await page.getByRole('button', {name:'历史任务', exact:false}).click();
    assert(await page.locator('#history-view').isVisible());
    assert((await page.locator('#task-history-list').innerText()).includes(saved.request));
    await page.getByRole('button', {name:'新建作业', exact:false}).click();
    assert.equal(tasks.length, 1, 'new assignment must preserve saved tasks');
    await page.getByRole('button', {name:'排序算法', exact:false}).click();
    assert((await page.locator('#agent-prompt').inputValue()).includes('排序算法'));
    await page.getByRole('button', {name:'开始生成作业', exact:true}).click();
    await page.locator('.agent-current').waitFor({state:'visible'});
    assert.equal(submissions.length, 1);
    assert.equal(submissions[0].execute, false);
    await page.getByRole('button', {name:'新建作业', exact:false}).click();
    await page.waitForFunction(() => document.querySelector('#agent-tasks').textContent === '');
    assert.equal(await page.locator('#agent-prompt').inputValue(), '');
    assert.equal(tasks.length, 2);
    assert.equal(await page.locator('#workspace-feedback').innerText(), '', 'new assignment must clear old status messages');
    await page.getByRole('button', {name:'课程资料', exact:true}).click();
    assert(await page.locator('#material-library').isVisible());
    assert.equal(await page.locator('#planning-settings').isVisible(), false);
    await page.getByRole('button', {name:'作业审核', exact:true}).click();
    await page.getByRole('button', {name:'自定义组卷 →', exact:true}).click();
    assert(await page.locator('#planning-settings').isVisible());
    tasks = [{id:'active-fixture', status:'running', request:'正在执行的作业', files:[]}, saved];
    await page.reload();
    await page.waitForFunction(() => document.querySelector('#agent-start').disabled);
    assert((await page.locator('#agent-tasks').innerText()).includes('正在执行的作业'));
    assert(await page.locator('#agent-stop-current').isVisible());
    tasks = [saved];
    await page.reload();
    await page.waitForFunction(() => !document.querySelector('#agent-start').disabled);
    await page.setViewportSize({width:390, height:844});
    await page.waitForFunction(() => document.querySelector('.sidebar').getBoundingClientRect().right <= 1);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.getByRole('button', {name:'展开导航', exact:true}).click();
    await page.getByRole('button', {name:'历史任务', exact:false}).click();
    assert(await page.locator('#history-view').isVisible());
    assert.deepEqual(errors, []);
    console.log('PASS: clean entry, preserved history, blank-input guard, local submission, active-task recovery, workbench navigation and mobile layout. Fixture only.');
  } finally {
    await browser.close();
  }
})().catch(error => {console.error(error); process.exitCode = 1;}).finally(() => server.close());
