/* Optional integration checks. See docs/TESTING.txt for browser setup. */
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const path=require('node:path');
const {spawn}=require('node:child_process');
const {createRequire}=require('node:module');
const root=path.resolve(__dirname,'..');
const out=path.resolve(process.env.VELTRAH_QA_OUTPUT||path.join(root,'evidence','browser'));
const httpPort=19765,wsPort=19000,url=`http://127.0.0.1:${httpPort}`;
const results=[],errors=[],external=[],trackers=new Set();let server,browser,page,serverLog='';
const pause=ms=>new Promise(r=>setTimeout(r,ms));
async function waitFor(check,ms=10000){const start=Date.now();let error;while(Date.now()-start<ms){try{const r=await check();if(r)return r;}catch(e){error=e;}await pause(50);}throw error||Error('Timed out');}
async function startServer(){
 server=spawn(process.env.VELTRAH_TEST_PYTHON||'python3',['-S','run_demo.py','--http-port',String(httpPort),'--ws-port',String(wsPort)],{cwd:root,stdio:['ignore','pipe','pipe']});
 server.stdout.on('data',b=>serverLog+=b);server.stderr.on('data',b=>serverLog+=b);
 await waitFor(async()=>{const r=await fetch(url+'/health');return r.ok;});
}
async function stopServer(){if(!server||server.exitCode!==null)return;const owned=server;const exited=new Promise(r=>owned.once('exit',r));owned.kill('SIGINT');await Promise.race([exited,pause(4500).then(()=>{if(owned.exitCode===null)owned.kill('SIGTERM');})]);}
async function check(name,fn){const start=Date.now();console.log('CHECK',name);let timer;try{await Promise.race([fn(),new Promise((_,rej)=>{timer=setTimeout(()=>rej(Error('Check exceeded 25 seconds')),25000);})]);results.push({name,status:'passed',duration_ms:Date.now()-start});console.log('PASS',name);}catch(e){results.push({name,status:'failed',error:e.message});throw e;}finally{clearTimeout(timer);}}
async function ready(p=page){await p.getByTestId('reply-1').waitFor({state:'visible'});await waitFor(async()=>await p.getByTestId('notice').textContent().then(t=>t.includes('ready')));}
async function reset(){await page.getByTestId('reset-button').click();await ready();}
async function draftIs(text){await waitFor(async()=>await page.getByTestId('draft-text').textContent().then(t=>t===text));}
async function count(name){return Number(await page.getByTestId(name+'-count').textContent());}
async function pointFor(testid){const b=await page.getByTestId(testid).boundingBox();const v=page.viewportSize();return {x:(b.x+b.width/2)/v.width,y:(b.y+b.height/2)/v.height};}
async function tracker(source){
 const ws=new WebSocket(`ws://127.0.0.1:${wsPort}`);
 trackers.add(ws);
 let timer;try{await Promise.race([new Promise((res,rej)=>{ws.onopen=res;ws.onerror=()=>rej(Error('Tracker WebSocket open failed'));}),new Promise((_,rej)=>{timer=setTimeout(()=>rej(Error('Tracker open timeout')),5000);})]);}finally{clearTimeout(timer);}
 const ack=new Promise((res,rej)=>{const handler=e=>{if(JSON.parse(e.data).type==='tracker_ack'){clearTimeout(tm);ws.removeEventListener('message',handler);res();}};const tm=setTimeout(()=>{ws.removeEventListener('message',handler);rej(Error('Tracker handshake timeout'));},5000);ws.addEventListener('message',handler);});
 ws.send(JSON.stringify({type:'tracker_hello'}));await ack;
 return {ws,send:(p,valid=true)=>{if(ws.readyState===WebSocket.OPEN)ws.send(JSON.stringify({type:'tracker_coordinates',source,valid,...(valid?p:{})}));},async hold(p,ms){const start=Date.now();while(Date.now()-start<ms){this.send(p);await pause(25);}},async close(){trackers.delete(ws);if(ws.readyState===WebSocket.CLOSED)return;await new Promise(r=>{ws.addEventListener('close',r,{once:true});ws.close();});}};
}
async function main(){
 await fs.mkdir(out,{recursive:true});await startServer();
 const launch=process.env.VELTRAH_BROWSER_ADAPTER?require(path.resolve(process.env.VELTRAH_BROWSER_ADAPTER)).launch:()=>createRequire(path.join(root,'qa','package.json'))('playwright').chromium.launch({headless:true});
 browser=await launch();const context=await browser.newContext({viewport:{width:1440,height:1000},acceptDownloads:true});
 context.on('request',r=>{if(!/^(http:\/\/(127\.0\.0\.1|localhost)(:|\/)|file:|blob:|data:)/.test(r.url()))external.push(r.url());});
 page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
 await page.goto(url);await ready();
 await check('Live Python/WebSocket fixture labels and four options',async()=>{
  assert.equal(await page.getByTestId('connection-status').textContent(),'Local Python backend');assert.equal(await page.locator('[data-testid^="reply-"]').count(),4);assert.equal(await count('committed'),0);
 });
 await page.screenshot({path:path.join(out,'live-start.png'),fullPage:true});
 await check('Stationary mouse dwell selects once without committing',async()=>{
  const option=page.getByTestId('reply-1'),text=(await option.innerText()).replace(/^01\s*/,'').replace(/\s*↗$/,'').trim();
  const b=await option.boundingBox();await page.mouse.move(b.x+b.width/2,b.y+b.height/2);await pause(1000);await draftIs(text);await pause(1000);assert.equal(await count('selected'),1);assert.equal(await count('committed'),0);
 });
 await check('Escape cancels and stationary hover does not select again',async()=>{
  await page.keyboard.press('Escape');await pause(900);assert.equal(await count('selected'),1);assert.equal(await count('cancelled'),1);assert.equal(await page.getByTestId('confirm-button').isEnabled(),false);
 });
 await check('Looking away before dwell completes cancels progress',async()=>{
  await page.mouse.move(5,5);const b=await page.getByTestId('reply-2').boundingBox();await page.mouse.move(b.x+50,b.y+20);await pause(200);await page.mouse.move(5,5);await pause(800);assert.equal(await count('selected'),1);
 });
 await check('Keyboard selection requires separate explicit confirmation',async()=>{
  await page.getByTestId('input-mode').selectOption('keyboard');await page.getByTestId('reply-1').focus();await page.keyboard.press('2');assert.equal(await page.getByTestId('confirm-button').isEnabled(),true);assert.equal(await count('committed'),0);await page.getByTestId('confirm-button').focus();await page.keyboard.press('Enter');await page.getByTestId('selection-result').waitFor();assert.equal(await count('committed'),1);
 });
 await reset();
 await check('Scenario changes invalidate an existing draft',async()=>{
  await page.getByTestId('reply-1').click();await page.getByTestId('scenario-select').selectOption('logistics');await ready();assert.equal(await page.getByTestId('confirm-button').isEnabled(),false);assert.equal(await count('committed'),1);
 });
 await check('Simulated generator failure and recovery do not commit',async()=>{
  await page.getByTestId('failure-button').click();await page.getByTestId('empty-state').waitFor();assert.equal(await page.getByTestId('confirm-button').isEnabled(),false);await page.getByTestId('recover-button').click();await ready();assert.equal(await count('committed'),1);
 });
 await check('Simulated response delay clears actions then restores a fresh trial',async()=>{
  const start=Date.now();await page.getByTestId('delay-button').click();await page.getByTestId('empty-state').waitFor();await ready();assert.ok(Date.now()-start>=1500);assert.equal(await count('committed'),1);
 });
 await check('Clearly labeled internal synthetic gaze selects a draft only',async()=>{
  await page.getByTestId('input-mode').selectOption('synthetic');await page.getByTestId('replay-button').click();await waitFor(()=>page.getByTestId('confirm-button').isEnabled());assert.equal(await count('committed'),1);await page.getByTestId('confirm-button').click();await page.getByTestId('selection-result').waitFor();assert.equal(await count('committed'),2);
 });
 await reset();
 await check('External synthetic coordinate replay reaches UI and lost input cancels',async()=>{
  const t=await tracker('synthetic');try{await t.hold(await pointFor('reply-1'),900);await waitFor(()=>page.getByTestId('confirm-button').isEnabled());t.send({},false);await waitFor(async()=>!(await page.getByTestId('confirm-button').isEnabled()));assert.equal(await count('committed'),2);}finally{await t.close();}
 });
 await check('Synthetic samples expire when the producer stops updating',async()=>{
  await page.getByTestId('reset-button').click();await ready();const t=await tracker('synthetic');try{await t.hold(await pointFor('reply-2'),200);await pause(1100);assert.equal(await page.getByTestId('confirm-button').isEnabled(),false);}finally{await t.close();}
 });
 await check('Camera source gate and stale/lost cancellation using protocol stubs only',async()=>{
  await reset();const t=await tracker('camera');let timer;try{
   const p=await pointFor('reply-3');timer=setInterval(()=>t.send(p),25);await waitFor(async()=>!(await page.locator('option[value="camera"]').isDisabled()));await page.getByTestId('input-mode').selectOption('camera');await page.bringToFront();await page.evaluate(()=>window.dispatchEvent(new Event('focus')));await waitFor(()=>page.getByTestId('confirm-button').isEnabled());clearInterval(timer);timer=null;await pause(650);assert.equal(await page.getByTestId('confirm-button').isEnabled(),false);assert.equal(await count('committed'),2);
  }finally{if(timer)clearInterval(timer);t.send({},false);await t.close();}
 });
 await check('Input mode and window blur clear draft selections',async()=>{
  await page.getByTestId('input-mode').selectOption('keyboard');await page.getByTestId('reply-1').click();await page.getByTestId('input-mode').selectOption('mouse');assert.equal(await page.getByTestId('confirm-button').isEnabled(),false);await page.getByTestId('reply-1').click();await page.evaluate(()=>window.dispatchEvent(new Event('blur')));assert.equal(await page.getByTestId('confirm-button').isEnabled(),false);await page.evaluate(()=>window.dispatchEvent(new Event('focus')));
 });
 await check('Disconnect clears drafts; reconnect starts fresh without resend',async()=>{
  await page.getByTestId('reply-2').click();await stopServer();await waitFor(async()=>await page.getByTestId('connection-status').textContent().then(x=>x.includes('offline')));assert.equal(await page.getByTestId('confirm-button').isEnabled(),false);await startServer();await ready();assert.equal(await count('committed'),2);assert.equal(await page.getByTestId('confirm-button').isEnabled(),false);
 });
 await check('Metrics export excludes message text and raw gaze coordinates',async()=>{
  const download=page.waitForEvent('download');await page.getByRole('button',{name:'Export session metrics'}).click();const d=await download;const target=path.join(out,'sample-session-metrics.json');await d.saveAs(target);const m=JSON.parse(await fs.readFile(target,'utf8'));assert.equal(m.contains_message_content,false);assert.equal(m.contains_raw_gaze,false);assert.ok(m.events.length>10);assert.equal(JSON.stringify(m).includes('Can we meet'),false);
 });
 await check('Independent browser tabs keep local selections separate',async()=>{
  const p=await context.newPage();try{await p.goto(url);await ready(p);await p.getByTestId('reply-4').click();await p.getByTestId('confirm-button').click();await p.getByTestId('selection-result').waitFor();assert.equal(await count('committed'),2);assert.equal(await page.getByTestId('reply-1').isVisible(),true);}finally{await p.close();await page.bringToFront();}
 });
 await check('Narrow viewport has no horizontal overflow and retains controls',async()=>{
  await page.setViewportSize({width:390,height:844});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));await page.getByTestId('input-mode').scrollIntoViewIfNeeded();assert.equal(await page.getByTestId('input-mode').isVisible(),true);await page.screenshot({path:path.join(out,'narrow-viewport.png'),fullPage:true});await page.setViewportSize({width:1440,height:1000});
 });
 if(process.env.VELTRAH_OFFLINE_HTML){await check('Single-file preview opens offline with browser-only fixtures',async()=>{
  await page.goto(require('node:url').pathToFileURL(path.resolve(process.env.VELTRAH_OFFLINE_HTML)).href);await ready();assert.equal(await page.getByTestId('connection-status').textContent(),'Browser-only fixtures');await page.getByTestId('reply-2').click();await page.getByTestId('confirm-button').click();await page.getByTestId('selection-result').waitFor();await page.getByTestId('reset-button').click();await ready();await page.getByTestId('failure-button').click();await page.getByTestId('empty-state').waitFor();await page.getByTestId('recover-button').click();await ready();await page.screenshot({path:path.join(out,'offline-preview.png'),fullPage:true});
 });}
 await check('No page exceptions or external HTTP requests',async()=>{assert.deepEqual(errors,[]);assert.deepEqual(external,[]);});
 console.log(JSON.stringify({passed:results.length,browser:await browser.version()}));
}
main().catch(e=>{console.error(e.stack);process.exitCode=1;}).finally(async()=>{
 const info={checked_at:new Date().toISOString(),scope:'Automated local software checks only. Camera-source checks use protocol stubs, not real camera data.',results,page_errors:errors,external_http_requests:external};
 await fs.mkdir(out,{recursive:true});await fs.writeFile(path.join(out,'browser-results.json'),JSON.stringify(info,null,2));await fs.writeFile(path.join(out,'server-log.txt'),serverLog);
 for(const ws of trackers)ws.close();await browser?.close();await stopServer();
});
