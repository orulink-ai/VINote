import assert from 'node:assert/strict';
import { mkdirSync } from 'node:fs';
import { chromium } from 'playwright';
const base = 'http://127.0.0.1:3100';
const out = '../docs/reviews'; mkdirSync(out, {recursive:true});
const browser=await chromium.launch({channel:'msedge',headless:true,args:['--no-proxy-server']});
const page=await browser.newPage({viewport:{width:760,height:600},locale:'zh-CN'});
await page.addInitScript(()=>{const state=new URL(location.href).searchParams.get('preview');localStorage.removeItem('vinote:import-receipt:fixture-owner:note');if(state)localStorage.setItem('vinote:import-receipt:fixture-owner:note',JSON.stringify({id:state,submissionState:'accepted',workspace:{scope:'personal'},meeting:false,sourceType:'video',sourceUrl:'https://example.invalid/source',createdAt:'2026-11-04T10:00:00Z'}));});
let writes=0; const errors=[];page.on('pageerror',e=>(errors.push(e.message),console.log('PAGE ERROR',e.message)));
await page.route('**/*',async route=>{
 const request=route.request(),url=new URL(request.url());
 if(!['127.0.0.1','localhost'].includes(url.hostname))return route.abort();
 if(!url.pathname.startsWith('/api/'))return route.continue();
 if(request.method()!=='GET'){writes++;return route.abort();}
 const json=body=>route.fulfill({contentType:'application/json',body:JSON.stringify(body)});
 if(url.pathname==='/api/auth/session')return json({authenticated:true,user:{id:'fixture-owner',email:'fixture@example.invalid'}});
 if(url.pathname==='/api/preferences')return json({language:'zh-CN'});
 if(url.pathname==='/api/task/running')return json({task_id:'running',status:'transcribing',message:'正在转写完整音频',processed_seconds:90,total_seconds:600,retryable:false});
 if(url.pathname==='/api/task/failed')return json({task_id:'failed',status:'failed',message:'下载未完成，原链接已保留。',failed_stage:'downloading',retryable:true});
 if(url.pathname==='/api/notes/fixture-note')return json({id:'fixture-note',title:'产品需求评审记录',content:'# 产品需求评审记录\n\n## 本次结论\n\n优先完成资料导入与记录查阅。\n\n## 后续事项\n\n- 核对来源文件\n- 整理评审意见',source_type:'text',status:'done',scope:'personal',created_at:'2026-11-04T10:00:00Z',updated_at:'2026-11-04T10:00:00Z'});
 if(url.pathname.endsWith('/versions'))return json([]);
 if(url.pathname.endsWith('/recording'))return json({available:false});
 if(url.pathname.endsWith('/transcript'))return json({full_text:'',segments:[],metadata:{}});
 if(url.pathname.endsWith('/share'))return json({share_enabled:false});
 if(url.pathname.includes('/feishu/automatic-deliveries/local/'))return route.fulfill({status:404,contentType:'application/json',body:'{}'});
 if(url.pathname.includes('/feishu/deliveries'))return json(null);
 if(url.pathname==='/api/notes')return json([{id:'fixture-note',title:'示例记录',content:'示例正文',source_type:'video',status:'done',scope:'personal',project:'产品需求与会议资料归档',created_at:'2026-11-04T00:00:00Z',updated_at:'2026-11-04T00:00:00Z'}]);
 if(url.pathname==='/api/teams')return json([{id:'fixture-team',name:'产品与研发协作空间',owner_id:'fixture-owner',current_user_role:'owner',member_count:1,created_at:'2026-11-04T00:00:00Z',updated_at:'2026-11-04T00:00:00Z',members:[{id:'fixture-member',user_id:'fixture-owner',email:'fixture@example.invalid',role:'owner',joined_at:'2026-11-04T00:00:00Z'}]}]);
 if(url.pathname==='/api/feishu/status')return json({configured:false,connected:false,groups:[]});
 if(/files|profiles|models|receipts/.test(url.pathname))return json([]);
 return json({});
});
try{
 for(const width of [1440,760]) {
 await page.setViewportSize({width,height:width===760?600:900});
 for(const [route,name]of[['/settings/feishu','feishu-detail-audit'],['/notes','notes-detail-audit']]){
 await page.goto(base+route,{waitUntil:'networkidle'});
 if(name==='note-edit')await page.getByRole('button',{name:'编辑',exact:true}).click();
 await page.evaluate(()=>document.fonts.ready);await page.waitForTimeout(300);
 await page.screenshot({path:out+'/2026-11-04-'+name+'-'+width+'.png'});
 assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),name+' overflow');
 }
 }
 assert.equal(writes,0); assert.deepEqual(errors,[]);console.log('Feishu and Notes synthetic states, 1440 and 760, no horizontal overflow, no API writes.');
}finally{await browser.close();}
