import { act, cleanup, renderHook } from '@testing-library/react';
import { beforeEach, afterEach, expect, it, vi } from 'vitest';
import { useTaskCenter } from './useTaskCenter';
import { apiJson } from '@/lib/api';
import { useAppModeStore } from '@/stores/appModeStore';
import { useAuthStore } from '@/stores/authStore';
vi.mock('@/lib/api', async original => ({ ...await original<typeof import('@/lib/api')>(), apiJson: vi.fn() }));
const api = vi.mocked(apiJson);
const flush = async () => { await act(async () => { for (let i=0;i<20;i++) await Promise.resolve() }) };
beforeEach(() => { vi.useFakeTimers(); api.mockReset(); useAuthStore.setState({user:{id:'owner'} as never}); Object.defineProperty(document,'hidden',{configurable:true,value:false}) });
afterEach(() => { cleanup(); vi.useRealTimers(); });
it('tracks independent stages, measured audio progress and exact saved completion without writes', async () => {
 api.mockImplementation(async path => path === '/api/notes' ? [{id:'saved-b',task_id:'b',status:'done'}] : path.endsWith('/a') ? {task_id:'a',status:'transcribing',processed_seconds:20,total_seconds:80,progress:99} : path.endsWith('/b') ? {task_id:'b',status:'success',result:{task_id:'b',title:'B',markdown:'body'}} : {task_id:'c',status:'failed',message:'音频读取失败'});
 const {result}=renderHook(()=>useTaskCenter('owner',['a','b','c'],true));await flush();
 expect(result.current.a).toMatchObject({label:'转写中',measure:'已转写 20 / 80 秒'});
 expect(result.current.b).toMatchObject({noteId:'saved-b',label:'已完成'});
 expect(result.current.c).toMatchObject({failed:true,message:'音频读取失败'});
 await act(async()=>vi.advanceTimersByTimeAsync(4000));
 expect(api.mock.calls.filter(([p])=>p==='/api/task/b')).toHaveLength(1);
 expect(api.mock.calls.every(([,i])=>!i?.method)).toBe(true);
});
it('bounds active GETs at three and never overlaps a polling cycle', async () => {
 const pending: ((v:unknown)=>void)[]=[];api.mockImplementation(()=>new Promise(r=>pending.push(r)));
 renderHook(()=>useTaskCenter('owner',['a','b','c','d'],true));await flush();expect(pending).toHaveLength(3);
 await act(async()=>vi.advanceTimersByTimeAsync(12000));expect(pending).toHaveLength(3);
 await act(async()=>pending[0]({task_id:'a',status:'transcribing'}));await flush();expect(pending).toHaveLength(4);
});
it('preserves the last stage on read failure and slows hidden polling then refreshes on visible', async () => {
 api.mockResolvedValueOnce({task_id:'a',status:'summarizing',progress:80}).mockRejectedValue(new Error('offline'));
 const {result}=renderHook(()=>useTaskCenter('owner',['a'],true));await flush();expect(result.current.a.measure).toBeUndefined();
 Object.defineProperty(document,'hidden',{configurable:true,value:true});act(()=>document.dispatchEvent(new Event('visibilitychange')));
 await act(async()=>vi.advanceTimersByTimeAsync(5000));expect(api).toHaveBeenCalledTimes(1);
 Object.defineProperty(document,'hidden',{configurable:true,value:false});act(()=>document.dispatchEvent(new Event('visibilitychange')));await flush();
 expect(result.current.a).toMatchObject({label:'生成内容中',unavailable:true,failed:false});
});
it('rejects delayed old-owner results even after batched owner ABA and stops on unmount', async () => {
 let finish!:(v:unknown)=>void;api.mockImplementation(()=>new Promise(r=>{finish=r}));
 const {result,unmount}=renderHook(()=>useTaskCenter('owner',['a'],true));await flush();
 const oldFinish=finish;
 act(()=>{useAuthStore.setState({user:{id:'other'} as never});useAuthStore.setState({user:{id:'owner'} as never})});
 await act(async()=>oldFinish({task_id:'a',status:'failed',message:'stale'}));expect(result.current.a?.message).not.toBe('stale');
 unmount();const count=api.mock.calls.length;await act(async()=>vi.advanceTimersByTimeAsync(60000));expect(api).toHaveBeenCalledTimes(count);
});
it('keeps complete but unsaved output recoverable and rejects mismatched task identity', async()=>{
 api.mockImplementation(async p=>p==='/api/notes'?[]:p.endsWith('/a')?{task_id:'a',status:'success',result:{task_id:'a',title:'A',markdown:'text'}}:{task_id:'other',status:'failed'});
 const {result}=renderHook(()=>useTaskCenter('owner',['a','b'],true));await flush();expect(result.current.a).toMatchObject({complete:true,label:'生成完成，待保存'});expect(result.current.a.noteId).toBeUndefined();expect(result.current.b).toMatchObject({unavailable:true,failed:false});
});

it('resolves only the exact uncertain operation then follows its accepted task without resubmission',async()=>{
 api.mockImplementation(async p=>p==='/api/source-requests/op'?{operation_id:'op',state:'accepted',task_id:'resolved'}:{task_id:'resolved',status:'summarizing'});
 const {result}=renderHook(()=>useTaskCenter('owner',[],true,0,['op']));await flush();
 expect(result.current['operation:op']).toMatchObject({label:'生成内容中'});
 expect(api.mock.calls.map(([p])=>p)).toEqual(['/api/source-requests/op','/api/task/resolved']);
 await act(async()=>vi.advanceTimersByTimeAsync(4000));expect(api.mock.calls.filter(([p])=>p.includes('source-requests'))).toHaveLength(1);
});
it('keeps reserved and mismatched receipts unverified without starting their tasks',async()=>{
 api.mockImplementation(async p=>p.endsWith('/reserved')?{operation_id:'reserved',state:'reserved',task_id:'not-started'}:{operation_id:'another',state:'accepted',task_id:'wrong'});
 const {result}=renderHook(()=>useTaskCenter('owner',[],true,0,['reserved','wrong']));await flush();
 expect(result.current['operation:reserved'].label).toBe('已登记，等待受理');expect(result.current['operation:wrong'].unavailable).toBe(true);
 expect(api.mock.calls.every(([p])=>p.startsWith('/api/source-requests/'))).toBe(true);
});
it('finds a note saved later without repolling or regenerating the completed model result',async()=>{
 let saved=false;api.mockImplementation(async p=>p==='/api/notes'?(saved?[{id:'note',task_id:'a',status:'done'}]:[]):{task_id:'a',status:'success',result:{task_id:'a',title:'A',markdown:'text'}});
 const {result}=renderHook(()=>useTaskCenter('owner',['a'],true));await flush();expect(result.current.a.noteId).toBeUndefined();saved=true;
 await act(async()=>vi.advanceTimersByTimeAsync(4000));expect(result.current.a.noteId).toBe('note');expect(api.mock.calls.filter(([p])=>p==='/api/task/a')).toHaveLength(1);
 const count=api.mock.calls.length;await act(async()=>vi.advanceTimersByTimeAsync(20000));expect(api).toHaveBeenCalledTimes(count);
});

it('invalidates late reads across a batched service Origin change and return',async()=>{
 let finish!:(v:unknown)=>void;api.mockImplementation(()=>new Promise(r=>{finish=r}));
 const original=useAppModeStore.getState().config;const {result}=renderHook(()=>useTaskCenter('owner',['a'],true));await flush();const old=finish;
 act(()=>{useAppModeStore.setState({config:{...original,server_url:'https://another.invalid'} as never});useAppModeStore.setState({config:original})});
 await act(async()=>old({task_id:'a',status:'failed',message:'wrong origin'}));expect(result.current.a?.message).not.toBe('wrong origin');
});

it('uses a known precise stage for active work without overriding failure or complete outcomes',async()=>{
 api.mockImplementation(async p=>p==='/api/notes'?[]:p.endsWith('/active')?{task_id:'active',status:'transcribing',stage:'diarizing'}:p.endsWith('/failed')?{task_id:'failed',status:'failed',stage:'summarizing'}:p.endsWith('/done')?{task_id:'done',status:'success',stage:'transcribing',result:{task_id:'done',title:'T',markdown:'body'}}:{task_id:'generic',status:'summarizing',stage:'unknown_provider_stage'});
 const {result}=renderHook(()=>useTaskCenter('owner',['active','failed','done','generic'],true));await flush();
 expect(result.current.active.label).toBe('分析说话人');expect(result.current.failed.label).toBe('处理失败');expect(result.current.done.label).toBe('生成完成，待保存');expect(result.current.generic.label).toBe('生成内容中');
});
it('looks up completed team tasks in their receipt workspace and stops polling after saving',async()=>{
 api.mockImplementation(async p=>p==='/api/notes?scope=team&team_id=team-1'?[{id:'team-note',task_id:'a',status:'done',scope:'team',team_id:'team-1'}]:p==='/api/notes'?[]:{task_id:'a',status:'success',result:{task_id:'a',title:'A',markdown:'text'}});
 const {result}=renderHook(()=>useTaskCenter('owner',['a'],true,0,[],{a:{scope:'team',teamId:'team-1'}}));await flush();
 expect(result.current.a).toMatchObject({noteId:'team-note',label:'已完成'});
 const count=api.mock.calls.length;await act(async()=>vi.advanceTimersByTimeAsync(20000));expect(api).toHaveBeenCalledTimes(count);
});
it('carries an uncertain operation workspace to its resolved task and rejects another team result',async()=>{
 let correct=false;api.mockImplementation(async p=>p==='/api/source-requests/op'?{operation_id:'op',state:'accepted',task_id:'a'}:p.startsWith('/api/notes')?[{id:'note',task_id:'a',status:'done',scope:'team',team_id:correct?'team-1':'other'}]:{task_id:'a',status:'success',result:{task_id:'a',title:'A',markdown:'text'}});
 const {result}=renderHook(()=>useTaskCenter('owner',[],true,0,['op'],{'operation:op':{scope:'team',teamId:'team-1'}}));await flush();
 expect(result.current['operation:op'].noteId).toBeUndefined();correct=true;
 await act(async()=>vi.advanceTimersByTimeAsync(4000));expect(result.current['operation:op'].noteId).toBe('note');
 expect(api.mock.calls.some(([p])=>p==='/api/notes?scope=team&team_id=team-1')).toBe(true);
});
it('records a verified operation-to-deleted-task binding and does not poll the deleted task',async()=>{
 localStorage.setItem('vinote:deleted-meeting-tasks:v1:owner', JSON.stringify(['deleted-task']));
 api.mockImplementation(async p=>p==='/api/source-requests/op-deleted'?{operation_id:'op-deleted',state:'accepted',task_id:'deleted-task'}:{task_id:'deleted-task',status:'failed'});
 renderHook(()=>useTaskCenter('owner',[],true,0,['op-deleted']));await flush();
 expect(api.mock.calls.map(([p])=>p)).toEqual(['/api/source-requests/op-deleted']);
 expect(JSON.parse(localStorage.getItem('vinote:deleted-meeting-operations:v1:owner')!)).toEqual({'op-deleted':'deleted-task'});
 localStorage.removeItem('vinote:deleted-meeting-tasks:v1:owner');localStorage.removeItem('vinote:deleted-meeting-operations:v1:owner');
});
