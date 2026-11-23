const fs = require('fs');
const path = require('path');
const assert = require('node:assert/strict');
const { chromium } = require(process.argv[2] || 'C:/Users/bohra/AppData/Local/npm-cache/_npx/420ff84f11983ee5/node_modules/playwright');
const root = path.resolve(__dirname, '../..');
const output = path.join(root, 'deliverables/demo-check');
fs.mkdirSync(output, { recursive: true });
const results = [], errors = [];
async function main() {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.on('pageerror', e => errors.push(e.message));
  const responses = [];
  page.on('response', async r => { if (r.url().endsWith('/api/compute')) responses.push({status:r.status(), data:await r.json()}); });
  async function check(name, fn) {
    try { await fn(); results.push({ name, pass:true }); console.log('PASS', name); }
    catch(e) { results.push({ name, pass:false, error:e.message }); console.log('FAIL', name, e.message); }
  }
  async function computeAction(fn) {
    const pending = page.waitForResponse(r => r.url().endsWith('/api/compute'), {timeout:20000});
    const [r] = await Promise.all([pending, fn()]); const d = await r.json(); assert.equal(r.status(),200,JSON.stringify(d));
    await page.waitForFunction(id => document.querySelector('#out')?.textContent.includes(id), d.case_id);
    return d;
  }
  const change=(selector,value)=>page.locator(selector).evaluate((el,value)=>{el.value=value;el.dispatchEvent(new Event('change',{bubbles:true}));},value);
  await check('Page and default calculation', async()=>{
    const d=await computeAction(()=>page.goto('http://127.0.0.1:8000', {waitUntil:'domcontentloaded'}));
    assert.equal(d.total.minor,472000); await page.screenshot({path:path.join(output,'desktop-initial.png'),fullPage:true});
  });
  await check('Cancellation preset changes the calculation', async()=>{
    const d=await computeAction(()=>page.click('#bar-preset-24h'));assert.equal(d.timeline.seconds_to_departure,86400);assert.equal(d.total.minor,364500);
  });
  await check('One minute across 96-hour boundary', async()=>{
    await computeAction(()=>change('#bar-canc-date','2026-01-11'));
    let d=await computeAction(()=>change('#bar-canc-time','18:00'));assert.equal(d.total.minor,472000);
    d=await computeAction(()=>change('#bar-canc-time','18:01'));assert.equal(d.total.minor,364500);
  });
  await check('UTC preset and preview agree with engine', async()=>{
    await computeAction(()=>page.selectOption('#bar-canc-tz','UTC'));
    const d=await computeAction(()=>page.click('#bar-preset-120h'));
    assert.equal(d.timeline.seconds_to_departure,432000);
    assert.equal(await page.inputValue('#bar-canc-time'),'12:30');
    assert.match(await page.locator('#bar-canc-preview').textContent(),/120\.00 h/);
    await computeAction(()=>page.selectOption('#bar-canc-tz','Asia/Kolkata'));
    await computeAction(()=>page.click('#bar-preset-120h'));
  });
  await check('Evidence opens and preserved policy downloads', async()=>{
    const row=page.locator('.tbl tbody tr').filter({has:page.locator('.lbl', {hasText:/^Base fare$/})});
    await row.locator('.ev-btn').click();assert(await row.locator('.ev-drawer').evaluate(e=>e.classList.contains('open')));
    const href=await row.locator('a[download]').getAttribute('href');const r=await page.request.get(new URL(href,page.url()).href);assert.equal(r.status(),200);assert((await r.body()).length>1000);
  });
  await check('All built-in ticket cases render', async()=>{
    const ids=await page.locator('.tk').evaluateAll(els=>els.map(e=>e.dataset.t));
    for(const id of ids){const d=await computeAction(()=>page.click(`[data-t="${id}"]`));assert(['COMPLETE','PARTIAL','NONE'].includes(d.total.status));}
  });
  await check('Coverage, source accordion, theme, and how-it-works tabs', async()=>{
    await page.click('[data-p="data"]');await page.waitForSelector('#covRows tr');assert.equal(await page.locator('#covRows tr').count(),5);
    await page.locator('.rule-h').first().click();assert(await page.locator('.rule').first().evaluate(e=>e.classList.contains('open')));
    await page.click('#themeBtn');assert.equal(await page.locator('html').getAttribute('data-theme'),'dark');await page.click('#themeBtn');
    await page.click('[data-p="how"]');assert(await page.locator('#p-how').isVisible());await page.click('[data-p="demo"]');
  });
  await check('Fare family survives moving to step 2 and back', async()=>{
    await page.click('#addBtn');await page.selectOption('#f-car','AI');
    await page.click('#nextBtn');await page.selectOption('#f-ff','ECONOMY_FLEX');await page.click('#backBtn2');await page.click('#nextBtn');
    assert.equal(await page.inputValue('#f-ff'),'ECONOMY_FLEX');await page.click('#cancelBtn');
  });
  // Test extraction integration with recorded responses. Live provider calls are separately tested.
  for(const file of ['01_spicejet_DEL-BOM.pdf','03_airindia_DEL-BOM_flex.pdf','06_makemytrip_invoice_LUMPED_TAX.pdf','08_indigo_BLR-HYD_photo.png']) {
    const responseFile=path.join(output,file+'.extraction.json');if(!fs.existsSync(responseFile))continue;
    const extraction=JSON.parse(fs.readFileSync(responseFile,'utf8'));
    await check('Upload review and compute: '+file, async()=>{
      if(await page.locator('#modal').isVisible())await page.click('#cancelBtn');
      await page.route('**/api/extract',route=>route.fulfill({json:extraction}));
      await page.setInputFiles('#file',path.join(root,'demo_uploads',file));await page.waitForSelector('#modal:not([hidden])');
      assert.equal(await page.inputValue('#f-base'),String(extraction.base_fare));
      await page.click('#nextBtn');
      if(file.startsWith('03_'))assert.equal(await page.inputValue('#f-ff'),'ECONOMY_FLEX');
      await page.click('#preset-120h');
      const d=await computeAction(()=>page.click('#runBtn'));if(file.startsWith('01_'))assert.equal(d.total.minor,472000);
      if(file.startsWith('06_'))assert.notEqual(d.total.status,'COMPLETE');
      await page.unroute('**/api/extract');
    });
  }
  await check('Missing extracted fields clear previous values',async()=>{
    if(await page.locator('#modal').isVisible())await page.click('#cancelBtn');
    await page.evaluate(()=>apply({carrier:null,carrier_seen:'Unknown',base_fare:null,departure:null,booking_date:null,total:null,fare_family:null,partially_used:true,passenger_count:2,missing:['carrier','base_fare','departure']}));
    assert.equal(await page.inputValue('#f-base'),'');assert.equal(await page.inputValue('#f-dep'),'');assert.equal(await page.inputValue('#f-car'),'');
    assert(await page.isChecked('#f-part'));await page.click('#cancelBtn');
  });
  await check('Recorded cancellation requires review and review retains the same case',async()=>{
    await computeAction(()=>page.click('[data-t="sg-before"]'));
    await change('#bar-canc-source','demo-external-reference');
    const d=await computeAction(()=>page.check('#bar-basis-act'));
    assert.equal(d.review_status,'REVIEW_REQUIRED');
    assert(d.assumptions.some(a=>a.code==='ACTUAL_RECORD_UNVERIFIED'));
    await page.fill(`#rev-name-${d.case_id}`,'Demo QA');
    await page.selectOption(`#rev-dec-${d.case_id}`,'ESCALATED');
    await page.fill(`#rev-reason-${d.case_id}`,'Specimen only; request original cancellation confirmation.');
    await page.click('.btn-rev');
    await page.waitForFunction(()=>document.querySelector('#out')?.textContent.includes('Review decision: ESCALATED'));
    assert((await page.locator('#out').textContent()).includes(d.case_id));
    const saved=await (await page.request.get(`http://127.0.0.1:8000/api/cases/${d.case_id}`)).json();
    assert.equal(saved.case.review.decision,'ESCALATED');assert(saved.audit_trail.some(e=>e.event==='review_recorded'));
    await computeAction(()=>page.check('#bar-basis-scen'));
  });
  if(process.env.DEMO_LIVE_EXTRACT==='1'||process.argv.includes('--live'))await check('Live browser PDF upload, responsive server, review, and saved calculation',async()=>{
    const start=Date.now();
    const pending=page.waitForResponse(r=>r.url().endsWith('/api/extract'),{timeout:65000});
    await page.setInputFiles('#file',path.join(root,'demo_uploads/01_spicejet_DEL-BOM.pdf'));
    await page.waitForSelector('#reading:not([hidden])');
    const healthStart=Date.now();
    const health=await page.request.get('http://127.0.0.1:8000/api/health',{timeout:3000});
    assert.equal(health.status(),200);assert(Date.now()-healthStart<3000);
    const extracted=await pending;assert.equal(extracted.status(),200);const fields=await extracted.json();
    await page.waitForSelector('#modal:not([hidden])');assert.equal(await page.inputValue('#f-car'),'SG');
    await page.click('#nextBtn');assert(await page.locator('#runBtn').isDisabled());
    await page.click('#preset-120h');const d=await computeAction(()=>page.click('#runBtn'));assert.equal(d.total.minor,472000);
    const saved=await (await page.request.get(`http://127.0.0.1:8000/api/cases/${d.case_id}`)).json();
    assert.equal(saved.case.request.extraction_ref,fields.extraction_ref);
    fs.writeFileSync(path.join(output,'live-browser-case.json'),JSON.stringify({case_id:d.case_id,seconds:(Date.now()-start)/1000,health_responded_during_extraction:true,total:d.total},null,2));
  });
  await check('Desktop and mobile layouts fit viewport', async()=>{
    if(await page.locator('#modal').isVisible())await page.click('#cancelBtn');
    await computeAction(()=>page.click('[data-t="sg-before"]'));
    await page.screenshot({path:path.join(output,'desktop.png'),fullPage:true});
    await page.setViewportSize({width:390,height:844});
    await page.screenshot({path:path.join(output,'mobile.png'),fullPage:true});
    const overflow=await page.evaluate(()=>({width:document.documentElement.scrollWidth,viewport:window.innerWidth,elements:[...document.querySelectorAll('body *')].filter(e=>e.getBoundingClientRect().right>innerWidth+1).slice(0,10).map(e=>({tag:e.tagName,class:e.className,width:e.getBoundingClientRect().width}))}));
    assert(overflow.width<=overflow.viewport+1,JSON.stringify(overflow));
  });
  await check('No uncaught browser exceptions',async()=>assert.deepEqual(errors,[]));
  fs.writeFileSync(path.join(output,'browser-results.json'),JSON.stringify({results,errors},null,2));
  await browser.close();if(results.some(r=>!r.pass))process.exitCode=1;
}
main().catch(e=>{console.error(e);process.exitCode=1});
