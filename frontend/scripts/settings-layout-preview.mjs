import assert from 'node:assert/strict';
import { mkdirSync } from 'node:fs';
import { chromium } from 'playwright';
const base = 'http://127.0.0.1:3100';
const out = '../docs/reviews'; mkdirSync(out, {recursive:true});
const browser=await chromium.launch({channel:'msedge',headless:true,args:['--no-proxy-server']});
const page=await browser.newPage({viewport:{width:760,height:600},locale:'zh-CN'});
let writes=0; const errors=[];page.on('pageerror',e=>errors.push(e.message));
await page.route('**/*',async route=>{
 const request=route.request(),url=new URL(request.url());
 if(!['127.0.0.1','localhost'].includes(url.hostname))return route.abort();
 if(!url.pathname.startsWith('/api/'))return route.continue();
 if(request.method()!=='GET'){writes++;return route.abort();}
 const json=body=>route.fulfill({contentType:'application/json',body:JSON.stringify(body)});
 if(url.pathname==='/api/auth/session')return json({authenticated:true,user:{id:'fixture-owner',email:'fixture@example.invalid'}});
 if(url.pathname==='/api/preferences')return json({language:'zh-CN'});
 if(url.pathname==='/api/notes')return json([{id:'fixture-note',title:'示例记录',content:'示例正文',source_type:'video',status:'done',scope:'personal',project:'产品需求与会议资料归档',created_at:'2026-11-04T00:00:00Z',updated_at:'2026-11-04T00:00:00Z'}]);
 if(url.pathname==='/api/teams')return json([{id:'fixture-team',name:'产品与研发协作空间',owner_id:'fixture-owner',current_user_role:'owner',member_count:1,created_at:'2026-11-04T00:00:00Z',updated_at:'2026-11-04T00:00:00Z',members:[{id:'fixture-member',user_id:'fixture-owner',email:'fixture@example.invalid',role:'owner',joined_at:'2026-11-04T00:00:00Z'}]}]);
 if(url.pathname==='/api/feishu/status')return json({configured:false,connected:false,groups:[]});
 if(/files|profiles|models|receipts/.test(url.pathname))return json([]);
 return json({});
});
try{
 for(const [route,name]of[['/settings','settings'],['/settings?tab=notifications','notification-settings'],['/settings/storage','storage'],['/team','team'],['/projects','projects']]){
 await page.goto(base+route,{waitUntil:'networkidle'});
 if(name==='projects') await page.evaluate(async()=>{
 const {useTeamStore}=await import(performance.getEntriesByType('resource').map(e=>e.name).find(n=>n.includes('/src/stores/teamStore.ts')) || '/src/stores/teamStore.ts'); useTeamStore.setState({currentWorkspace:{scope:'personal'}});
 const {useWorkspaceStore}=await import(performance.getEntriesByType('resource').map(e=>e.name).find(n=>n.includes('/src/stores/workspaceStore.ts')) || '/src/stores/workspaceStore.ts');
 useWorkspaceStore.setState({owner:'fixture-owner',ready:true,items:[{key:'fixture-content',title:'示例内容',source_type:'video',source_device:'fixture',created_at:'2026-11-04T00:00:00Z',updated_at:'2026-11-04T00:00:00Z',deleted:false}],details:{'fixture-content':{metadata:{project:'产品需求与会议资料归档'},content:'示例',versions:[]}}});
 });
 if(name==='team'){await page.getByRole('button',{name:/产品与研发协作空间/}).click();await page.getByRole('button',{name:'新建团队空间'}).click();}
 await page.evaluate(()=>document.fonts.ready); await page.waitForTimeout(250);
 await page.screenshot({path:`${out}/2026-11-04-${name}-760.png`,fullPage:true});
 if(name==='team') {await page.getByText('成员邮箱',{exact:true}).scrollIntoViewIfNeeded();await page.screenshot({path:out+'/2026-11-04-team-members-760.png'});}
 assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),name+' horizontal overflow');
 }
 assert.equal(writes,0); assert.deepEqual(errors,[]);console.log('5 synthetic pages, 760x600, no horizontal overflow, no API writes.');
}finally{await browser.close();}
