// Browser regression: requires Playwright and a local Chromium executable.
// Run from the repository root; CHROMIUM_PATH overrides the macOS default.
const {chromium}=require('playwright'),fs=require('fs'),assert=require('node:assert/strict');
const fn=require('./ui_source').functions('openSource');
(async()=>{
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
for(const width of [1200,390]){
const page=await browser.newPage({viewport:{width,height:900}});page.on('pageerror',e=>console.log('pageerror:',e.message));page.setDefaultTimeout(7000);let cached=false,fail=false,delay=0,calls=0;
await page.route('http://mail.test/**',async r=>{
const url=r.request().url();if(url.endsWith('/api/source'))return r.fulfill({json:{html:'<p>Original content <a href="https://example.test">Register</a></p>',external:[]}});
if(url.endsWith('/api/source/translate')){calls++;await new Promise(resolve=>setTimeout(resolve,delay));return r.fulfill({status:fail?500:200,json:fail?{error:'测试失败'}:{html:'<p>中文正文 <a href="https://example.test">报名</a></p>',subject:'中文标题',cached,elapsedMs:12}})}
return r.fulfill({contentType:'text/html',headers:{'Content-Security-Policy':"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-src 'self' about:; frame-ancestors 'none'"},body:`<!doctype html><html><head><meta charset="utf-8"><style>${fs.readFileSync('web/styles.css','utf8')}</style></head><body><button id="open" onclick="openSource({id:'test',subject:'Original title'})">打开</button><dialog id="source-dialog"><h2>原邮件</h2><div id="source-content"></div><button id="close" onclick="document.querySelector('dialog').close()">关闭</button></dialog><script>const getMailDetail=async m=>m;const token='fixture',$=id=>document.getElementById(id);function element(tag,text,cls){let e=document.createElement(tag);e.textContent=text||'';if(cls)e.className=cls;return e};${fn}</script></body></html>`})});
await page.goto('http://mail.test');await page.locator('#open').click();const frames=page.locator('iframe');
await page.frameLocator('iframe').first().getByText('Original content',{exact:false}).waitFor({state:'visible'});
await page.locator('.source-mode').nth(1).click();await page.frameLocator('iframe').nth(1).getByText('中文正文',{exact:false}).waitFor({state:'visible'});
for(let i=0;i<5;i++){await page.getByRole('button',{name:'原文',exact:true}).click();await page.frameLocator('iframe').first().getByText('Original content',{exact:false}).waitFor({state:'visible'});await page.getByRole('button',{name:'中文',exact:true}).click();await page.frameLocator('iframe').nth(1).getByText('中文正文',{exact:false}).waitFor({state:'visible'})}
assert.equal(calls,1);await page.locator('#close').click();cached=true;await page.locator('#open').click();await page.getByRole('button',{name:'中文',exact:true}).click();await page.getByText('已使用缓存译文；本次无需调用 AI。').waitFor();await page.frameLocator('iframe').nth(1).getByText('中文正文',{exact:false}).waitFor({state:'visible'});
await page.locator('#close').click();delay=200;await page.locator('#open').click();await page.getByRole('button',{name:'中文',exact:true}).click();await page.getByRole('button',{name:'原文',exact:true}).click();await page.getByText('已使用缓存译文；本次无需调用 AI。').waitFor();assert.equal(await frames.first().isVisible(),true);assert.equal(await frames.nth(1).isVisible(),false);
await page.getByRole('button',{name:'中文',exact:true}).click();await page.frameLocator('iframe').nth(1).getByText('中文正文',{exact:false}).waitFor({state:'visible'});
await page.screenshot({path:require('node:path').join(require('node:os').tmpdir(),`source-translation-fixed-${width}.png`)});
await page.locator('#close').click();fail=true;delay=0;await page.locator('#open').click();await page.getByRole('button',{name:'中文',exact:true}).click();await page.getByText('翻译失败：测试失败',{exact:false}).waitFor();await page.getByRole('button',{name:'原文',exact:true}).click();await page.frameLocator('iframe').first().getByText('Original content',{exact:false}).waitFor({state:'visible'});
fail=false;await page.getByRole('button',{name:'中文',exact:true}).click();await page.frameLocator('iframe').nth(1).getByText('中文正文',{exact:false}).waitFor({state:'visible'});
// Closing a pending request must not reopen the dialog or change a newer mail.
await page.locator('#close').click();delay=200;await page.locator('#open').click();await page.getByRole('button',{name:'中文',exact:true}).click();await page.locator('#close').click();await page.waitForTimeout(300);assert.equal(await page.locator('#source-dialog').isVisible(),false);
console.log(width+': visible original, first/cached Chinese, repeated switching, response race and error recovery pass');await page.close();}
await browser.close();})().catch(e=>{console.error(e);process.exit(1)});
