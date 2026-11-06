import { useEffect, useState } from 'react';
import { apiJson } from '@/lib/api';
import { useAuthStore } from '@/stores/authStore';
import { useAppModeStore } from '@/stores/appModeStore';
import { deletedMeetingOperation, deletedMeetingTasks, rememberDeletedMeetingOperation } from '@/lib/deletedMeetingTasks';
export type TaskWorkspace = { scope: 'personal' | 'team'; teamId?: string };
export type CenterTask = { label: string; status?: string; errorCode?: string; message?: string; measure?: string; progress?: number; title?: string; noteId?: string; complete: boolean; failed: boolean; terminal: boolean; unavailable?: boolean };
const labels: Record<string,string> = {pending:'等待处理',queued:'排队中',preparing:'准备来源',preparing_media:'准备资料',downloading:'下载中',transcribing:'转写中',diarizing:'分析说话人',parallel_analysis:'转写与说话人分析',aligning:'对齐转写',analyzing_video:'分析共享画面',summarizing:'生成内容中',screenshots:'整理画面',saving:'保存中',saving_result:'保存中'};
const initial = ():CenterTask => ({label:'正在读取状态',complete:false,failed:false,terminal:false});
/** Read-only task projection. No estimated percentages, retries or submission here. */
export function useTaskCenter(owner:string|undefined, taskIds:string[], enabled:boolean, refresh=0, operationIds:string[]=[], workspaces:Record<string,TaskWorkspace>={}):Record<string,CenterTask> {
 const origin=useAppModeStore(s=>s.config?.server_url);
 const ids=[...new Set(taskIds.filter(id=>/^[A-Za-z0-9_-]{1,160}$/.test(id)))].sort();
 const operations=[...new Set(operationIds.filter(id=>/^[A-Za-z0-9_-]{1,160}$/.test(id)&&(!owner||!deletedMeetingOperation(owner,id))))].sort();
 const destinations=Object.fromEntries(Object.entries(workspaces).sort(([a],[b])=>a.localeCompare(b)));
 const [visit,setVisit]=useState(0);
 const binding=JSON.stringify([owner,origin,enabled,ids,operations,destinations,refresh,visit]);
 const [snapshot,setSnapshot]=useState<{binding:string;states:Record<string,CenterTask>}>({binding:'',states:{}});
 useEffect(()=>{
  const controller=new AbortController();let timer:ReturnType<typeof setTimeout>|undefined;let running=false;
  const states:Record<string,CenterTask>=Object.fromEntries(ids.map(id=>[id,initial()]));
  const readSignal=()=>AbortSignal.any([controller.signal,AbortSignal.timeout(20000)]);
  const tasks=new Set(ids);const pendingOperations=new Set(operations);const resolved=new Map<string,string>();
  for(const operation of operations)states[`operation:${operation}`]={...initial(),label:'提交状态待核验'};
  const active=()=>!controller.signal.aborted&&useAuthStore.getState().user?.id===owner&&useAppModeStore.getState().config?.server_url===origin;
  const publish=()=>{if(active())setSnapshot({binding,states:{...states,...Object.fromEntries([...resolved].map(([operation,id])=>[`operation:${operation}`,states[id]]))}})};
  const clear=()=>{if(timer)clearTimeout(timer);timer=undefined};
  const unsubscribe=useAuthStore.subscribe((next,previous)=>{if(next.user?.id!==previous.user?.id){controller.abort();clear();setVisit(v=>v+1)}});
  const unsubscribeOrigin=useAppModeStore.subscribe((next,previous)=>{if(next.config?.server_url!==previous.config?.server_url){controller.abort();clear();setVisit(v=>v+1)}});
  const schedule=()=>{clear();if(active()&&enabled&&(pendingOperations.size>0||[...tasks].some(id=>!states[id].terminal||states[id].complete&&!states[id].noteId)))timer=setTimeout(()=>void cycle(),document.hidden?30000:4000)};
  const read=async(id:string)=>{
   try{
    const data=await apiJson<{task_id?:string;status:string;error_code?:string;stage?:string;message?:string;processed_seconds?:number;total_seconds?:number;result?:{task_id?:string;title?:string;markdown?:string}}>(`/api/task/${encodeURIComponent(id)}`,{signal:readSignal()});
    if(!active())return;
    if(!data||data.task_id!==id||typeof data.status!=='string'||data.result?.task_id&&data.result.task_id!==id)throw new Error('unverified');
    const failed=['failed','error'].includes(data.status);
    const complete=data.status==='success'&&!!data.result?.title?.trim()&&!!data.result?.markdown?.trim();
    const knownStage = typeof data.stage === 'string' && Object.prototype.hasOwnProperty.call(labels, data.stage) ? labels[data.stage] : undefined;
    const activeLabel = Object.prototype.hasOwnProperty.call(labels, data.status) ? knownStage || labels[data.status] : '状态待核验';
    const seconds=data.processed_seconds,total=data.total_seconds;
    const measure=data.status==='transcribing'&&typeof seconds==='number'&&Number.isFinite(seconds)&&seconds>=0&&typeof total==='number'&&Number.isFinite(total)&&total>0&&seconds<=total?`已转写 ${Math.round(seconds)} / ${Math.round(total)} 秒`:undefined;
    const progress=measure!==undefined ? Math.round(seconds! / total! * 100) : undefined;
    states[id]={status:data.status,errorCode:data.error_code,label:failed?'处理失败':complete?'生成完成，待保存':data.status==='success'?'结果待核验':activeLabel,message:typeof data.message==='string'?data.message:undefined,measure,progress,title:data.result?.title,failed,complete,terminal:failed||complete};publish();
   }catch{if(active()){states[id]={...states[id],unavailable:true};publish()}}
  };
  const cycle=async()=>{
   if(!active()||running||!enabled||!owner)return;
   running=true;clear();
   try{
    const resolveQueue=[...pendingOperations];let resolution=0;
    await Promise.all(Array.from({length:Math.min(3,resolveQueue.length)},async()=>{while(active()&&resolution<resolveQueue.length){const operation=resolveQueue[resolution++];try{
      const receipt=await apiJson<{operation_id:string;task_id?:string;state?:string}>(`/api/source-requests/${encodeURIComponent(operation)}`,{signal:readSignal()});
      if(!active())return;
      if(receipt.operation_id!==operation||!['reserved','accepted'].includes(receipt.state||''))throw new Error('unverified');
      if(receipt.state==='accepted'&&receipt.task_id&&/^[A-Za-z0-9_-]{1,160}$/.test(receipt.task_id)){
       if(deletedMeetingTasks(owner).has(receipt.task_id)){rememberDeletedMeetingOperation(owner,operation,receipt.task_id);pendingOperations.delete(operation);delete states[`operation:${operation}`];continue}
       tasks.add(receipt.task_id);states[receipt.task_id]??=initial();resolved.set(operation,receipt.task_id);pendingOperations.delete(operation)}
      else states[`operation:${operation}`]={...initial(),label:'已登记，等待受理'};
      publish();
    }catch{if(active()){states[`operation:${operation}`]={...states[`operation:${operation}`],unavailable:true};publish()}}}}));
    const queue=[...tasks].filter(id=>!states[id].terminal);let next=0;
    await Promise.all(Array.from({length:Math.min(3,queue.length)},async()=>{while(active()&&next<queue.length){const id=queue[next++];await read(id)}}));
    if(active()&&[...tasks].some(id=>states[id].complete&&!states[id].noteId)){
     const groups=new Map<string,{workspace:TaskWorkspace;ids:string[]}>();
     for(const id of tasks){
      if(!states[id].complete||states[id].noteId)continue;
      const operation=[...resolved].find(([,task])=>task===id)?.[0];
      const workspace=destinations[id]||(operation?destinations[`operation:${operation}`]:undefined)||{scope:'personal'};
      if(workspace.scope!=='personal'&&(workspace.scope!=='team'||typeof workspace.teamId!=='string'||!workspace.teamId))continue;
      const path=workspace.scope==='team'?'/api/notes?'+new URLSearchParams({scope:'team',team_id:workspace.teamId!}):'/api/notes';
      const group=groups.get(path)||{workspace,ids:[]};group.ids.push(id);groups.set(path,group);
     }
     for(const [path,{workspace,ids:groupIds}]of groups){
      if(!active())break;
      try{
       const notes=await apiJson<{id:string;task_id?:string;status?:string;scope?:string;team_id?:string|null}[]>(path,{signal:readSignal()});
       if(active()&&Array.isArray(notes)){
        for(const id of groupIds){
         const note=notes.find(n=>n.task_id===id&&typeof n.id==='string'&&n.id&&n.status==='done'
          &&(workspace.scope==='team'?n.scope==='team'&&n.team_id===workspace.teamId:(!n.scope||n.scope==='personal')&&!n.team_id));
         if(note)states[id]={...states[id],label:'已完成',noteId:note.id};
        }
        publish();
       }
      }catch{/* Result stays recoverable if note lookup fails. */}
     }
    }
   }finally{running=false;schedule()}
  };
  const visibility=()=>{clear();if(document.hidden)schedule();else void cycle()};
  publish();if(enabled&&owner&&(ids.length||operations.length))void cycle();document.addEventListener('visibilitychange',visibility);
  return()=>{controller.abort();clear();unsubscribe();unsubscribeOrigin();document.removeEventListener('visibilitychange',visibility)};
 },[binding]);
 return snapshot.binding===binding?snapshot.states:{};
}
