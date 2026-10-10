import { useEffect, useState, type FormEvent } from 'react';
import type { components } from './api-schema';
import type { apiClient } from './client';
import { parseSchedule } from './schedule-definition';

type Client = ReturnType<typeof apiClient>;
type Task = components['schemas']['Task'];
type Version = components['schemas']['ScheduleVersion'];
const base = '/api/v1/organizations/{organization_id}/workspaces/{workspace_id}' as const;
const schedulesPath = `${base}/schedules` as const;
const versionPath = `${schedulesPath}/{schedule_id}/versions/{number}` as const;
const taskPath = `${base}/tasks/{task_id}` as const;
function failure(error: unknown): string { return error && typeof error === 'object' && 'code' in error ? String(error.code) : 'Request could not be completed.'; }
export function Scheduling({ api, organization, workspace, project, canManage, userId, onOpen }: {
  api: Client; organization: string; workspace: string; project: string; canManage: boolean; userId: string;
  onOpen: (task: Task) => void;
}) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [view, setView] = useState<'all' | 'due_today' | 'overdue' | 'upcoming' | 'returned' | 'awaiting_review'>('all');
  const [mode, setMode] = useState<'personal' | 'team' | 'department' | 'project'>('personal');
  const [target, setTarget] = useState('');
  const [schedules, setSchedules] = useState<components['schemas']['Schedule'][]>([]);
  const [scheduleCursor, setScheduleCursor] = useState<string | null>(null);
  const [schedule, setSchedule] = useState('');
  const [version, setVersion] = useState<Version>();
  const [versions, setVersions] = useState<Version[]>([]);
  const [number, setNumber] = useState(1);
  const [preview, setPreview] = useState<Version>();
  const [source, setSource] = useState(JSON.stringify({ form_id: '', form_number: 1, recurrence: { kind: 'daily', timezone: 'UTC', starts_local: new Date().toISOString().slice(0,19) }, assignments: [{kind:'role',role:project?'ProjectManager':'OrganizationAdmin'}], due_after_seconds:28800, reminder_offsets:[0,86400] }, null, 2));
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [generation, setGeneration] = useState(0);
  const [lifecycle, setLifecycle] = useState<'active' | 'paused' | 'retired'>('paused');
  const [lifecyclePreview, setLifecyclePreview] = useState(false);
  const [reminders, setReminders] = useState<components['schemas']['Reminder'][]>([]);
  const path = {organization_id: organization, workspace_id: workspace};
  const query = {...(project ? {project_id:project}:{}),view,mode,...(target ? {target_id:target}:{})};
  useEffect(() => {
    let active = true;
    void api.GET(`${base}/tasks`, {params:{path, query}}).then(result => { if (active) {setTasks(result.data?.items ?? []);setCursor(result.data?.next_cursor ?? null);if (result.error) setMessage(failure(result.error));} }).catch(() => {if(active)setMessage('Inbox could not be loaded.');});
    return () => {active=false;};
  }, [api, organization, workspace, project, view, mode, target, generation]);
  useEffect(() => {
    let active = true;
    if(canManage) void api.GET(schedulesPath,{params:{path,query:project?{project_id:project}:{}}}).then(result => {if(active&&result.data){setSchedules(result.data.items);setScheduleCursor(result.data.next_cursor);}}).catch(()=>{if(active)setMessage('Schedules could not be loaded.');});
    return ()=>{active=false;};
  },[api,organization,workspace,project,canManage,generation]);
  useEffect(() => {
    let active=true; setVersion(undefined);setPreview(undefined);setLifecyclePreview(false);
    if(schedule) void api.GET(`${schedulesPath}/{schedule_id}/versions`,{params:{path:{...path,schedule_id:schedule}}}).then(result=>{if(active&&result.data){setVersions(result.data.items);const latest=result.data.items.at(-1);if(latest){setVersion(latest);setNumber(latest.number);setSource(JSON.stringify(latest.definition,null,2));}}}).catch(()=>{if(active)setMessage('Schedule versions could not be loaded.');});
    return ()=>{active=false;};
  },[api,organization,workspace,schedule]);
  async function run(action:()=>Promise<void>){setBusy(true);setMessage('');try{await action();}catch(error){setMessage(error instanceof Error?error.message:'Request failed.');}finally{setBusy(false);}}
  async function create(event:FormEvent<HTMLFormElement>){event.preventDefault();const data=new FormData(event.currentTarget);await run(async()=>{const result=await api.POST(schedulesPath,{params:{path},body:{name:String(data.get('schedule_name')),definition:parseSchedule(source),...(project?{project_id:project}:{})}});if(!result.data){setMessage(failure(result.error));return;}setSchedule(result.data.id);setGeneration(x=>x+1);setMessage('Schedule draft created.');});}
  function changeDefinition(update:(definition:components['schemas']['ScheduleDefinition'])=>components['schemas']['ScheduleDefinition']) {
    try {setSource(JSON.stringify(update(parseSchedule(source)),null,2));setPreview(undefined);}catch{setMessage('Correct the advanced definition before editing schedule properties.');}
  }
  async function activate(apply:boolean){if(!version)return;await run(async()=>{const result=await api.POST(`${versionPath}/activate`,{params:{path:{...path,schedule_id:schedule,number}},body:{expected_revision:version.revision??1,dry_run:!apply,...(apply&&preview?.content_sha256?{expected_sha256:preview.content_sha256}:{})}});if(!result.data){setMessage(failure(result.error));setPreview(undefined);return;}if(apply){setVersion(result.data);setPreview(undefined);setGeneration(x=>x+1);setMessage('Schedule activated.');}else{setPreview(result.data);setMessage('Activation preview ready. Review exact definition before applying.');}});}
  async function materialize(){await run(async()=>{const start=new Date();const end=new Date(start.getTime()+30*86400000);const result=await api.POST(`${schedulesPath}/{schedule_id}/materialize`,{params:{path:{...path,schedule_id:schedule}},body:{start:start.toISOString(),end:end.toISOString(),dry_run:false}});if(result.data){setMessage(`Generated ${result.data.created} new tasks.`);setGeneration(x=>x+1);}else setMessage(failure(result.error));});}
  async function claim(task:Task){await run(async()=>{const result=await api.POST(`${taskPath}/start`,{params:{path:{...path,task_id:task.id}},body:{expected_revision:task.revision??1}});if(result.data){setGeneration(x=>x+1);setMessage(result.data.kind==='generic'?'Task claimed. Acknowledge completion when the work is done.':'Task claimed. Complete its exact-version form.');if(result.data.kind!=='generic')onOpen(result.data);}else setMessage(failure(result.error));});}
  async function complete(task:Task){await run(async()=>{const result=await api.POST(`${taskPath}/complete`,{params:{path:{...path,task_id:task.id}},body:{expected_revision:task.revision??1}});if(result.data){setGeneration(x=>x+1);setMessage('Task completion recorded.');}else setMessage(failure(result.error));});}
  async function versionSave(){if(!version)return;await run(async()=>{const result=await api.PUT(versionPath,{params:{path:{...path,schedule_id:schedule,number}},body:{definition:parseSchedule(source),expected_revision:version.revision??1}});if(result.data){setVersion(result.data);setPreview(undefined);setMessage('Schedule draft saved.');}else setMessage(failure(result.error));});}
  async function clone(){await run(async()=>{const next=Math.max(...versions.map(x=>x.number),number)+1;const result=await api.POST(`${schedulesPath}/{schedule_id}/versions`,{params:{path:{...path,schedule_id:schedule}},body:{source_number:number,number:next}});if(result.data){setVersions(current=>[...current,result.data!]);setVersion(result.data);setNumber(next);setSource(JSON.stringify(result.data.definition,null,2));setPreview(undefined);setMessage('New schedule draft created.');}else setMessage(failure(result.error));});}
  async function changeLifecycle(apply:boolean){if(!version)return;await run(async()=>{const reason=(document.getElementById('schedule-reason') as HTMLInputElement).value;const result=await api.POST(`${versionPath}/lifecycle`,{params:{path:{...path,schedule_id:schedule,number}},body:{expected_revision:version.revision??1,state:lifecycle,reason,dry_run:!apply}});if(result.data){if(apply){setVersion(result.data);setLifecyclePreview(false);setMessage('Schedule lifecycle changed.');}else{setLifecyclePreview(true);setMessage('Lifecycle preview ready. Existing task history is preserved.');}}else setMessage(failure(result.error));});}
  return <section aria-label="Scheduling and My Work"><h2>My Work</h2><p>Workspace {workspace}{project&&` / Project ${project}`}</p><p role="status">{message}</p>
    <label>Task view<select value={view} onChange={e=>setView(e.target.value as typeof view)}><option value="all">All assigned work</option><option value="due_today">Due today</option><option value="overdue">Overdue</option><option value="upcoming">Upcoming</option><option value="returned">Returned</option><option value="awaiting_review">Waiting review</option></select></label>
    <label>Inbox scope<select value={mode} onChange={e=>setMode(e.target.value as typeof mode)}><option value="personal">Personal</option><option value="team">Team</option><option value="department">Department</option>{canManage&&<option value="project">Project / workspace</option>}</select></label>
    {(mode==='team'||mode==='department')&&<label>Inbox group ID<input value={target} onChange={e=>setTarget(e.target.value)} /></label>}
    <button disabled={busy} onClick={()=>setGeneration(x=>x+1)}>Refresh My Work</button>
    <ul>{tasks.map(task=><li key={task.id}><strong>{task.name}</strong> — {task.state} — due {new Date(task.due_at).toLocaleString(undefined,{timeZone:task.timezone})} ({task.timezone})
      {task.state==='open'&&<button disabled={busy} onClick={()=>void claim(task)}>Claim task</button>}{task.submission_id&&<button disabled={busy} onClick={()=>onOpen(task)}>Open task form</button>}
      {task.kind==='generic'&&task.state==='in_progress'&&task.claimant_id===userId&&<button disabled={busy} onClick={()=>void complete(task)}>Acknowledge completion</button>}
      {task.kind==='generic'&&<span> — Work acknowledgement{task.completed_at&&` recorded ${new Date(task.completed_at).toLocaleString()}`}</span>}
      <button disabled={busy} onClick={()=>void run(async()=>{const result=await api.GET(`${taskPath}/reminders`,{params:{path:{...path,task_id:task.id}}});if(result.data)setReminders(result.data.items);else setMessage(failure(result.error));})}>View reminders</button>
      {canManage&&['open','in_progress'].includes(task.state)&&<button disabled={busy} onClick={()=>void run(async()=>{const reason=prompt('Cancellation reason');if(!reason)return;const body={expected_revision:task.revision??1,reason,dry_run:true};const params={path:{...path,task_id:task.id}};const preview=await api.POST(`${taskPath}/cancel`,{params,body});if(!preview.data){setMessage(failure(preview.error));return;}if(!confirm('Cancel this task? Its submission and history will be retained.'))return;const result=await api.POST(`${taskPath}/cancel`,{params,body:{...body,dry_run:false}});if(result.data){setGeneration(x=>x+1);setMessage('Task cancelled.');}else setMessage(failure(result.error));})}>Cancel task</button>}
    </li>)}</ul>{!tasks.length&&<p>No work in this view.</p>}
    {cursor&&<button disabled={busy} onClick={()=>void run(async()=>{const result=await api.GET(`${base}/tasks`,{params:{path,query:{...query,cursor:cursor!}}});if(result.data){setTasks(current=>[...current,...result.data!.items]);setCursor(result.data.next_cursor);}else setMessage(failure(result.error));})}>Load more tasks</button>}
    <ul aria-label="Task reminders">{reminders.map(item=><li key={item.id}>Reminder: {new Date(item.scheduled_at).toLocaleString()}</li>)}</ul>
    {canManage&&<details><summary>Schedule administration</summary><form onSubmit={event=>void create(event)}><label>Schedule name<input name="schedule_name" required maxLength={120}/></label>
      <label>Schedule form ID<input onChange={e=>changeDefinition(d=>({...d,form_id:e.target.value}))}/></label>
      <label>Schedule form version<input type="number" min={1} defaultValue={1} onChange={e=>changeDefinition(d=>({...d,form_number:Number(e.target.value)}))}/></label>
      <label>Schedule recurrence<select defaultValue="daily" onChange={e=>changeDefinition(d=>({...d,recurrence:{...d.recurrence,kind:e.target.value as components['schemas']['Recurrence']['kind']}}))}><option value="daily">Daily</option><option value="weekly">Weekly</option><option value="monthly">Monthly</option><option value="one_time">One time (set timestamp below)</option><option value="rrule">RRULE (set rule below)</option><option value="shift">Shift (pin roster below)</option><option value="milestone">Milestone (pin milestone below)</option><option value="relative_event">Relative event (set event below)</option><option value="interval">Elapsed interval (set seconds below)</option></select></label>
      <label>Schedule timezone<input defaultValue="UTC" onChange={e=>changeDefinition(d=>({...d,recurrence:{...d.recurrence,timezone:e.target.value}}))}/></label>
      <label>Schedule local start<input type="datetime-local" defaultValue={new Date().toISOString().slice(0,16)} onChange={e=>changeDefinition(d=>({...d,recurrence:{...d.recurrence,starts_local:e.target.value}}))}/></label>
      <label>Schedule assignment role<select defaultValue={project?'ProjectManager':'OrganizationAdmin'} onChange={e=>changeDefinition(d=>({...d,assignments:[{kind:'role',role:e.target.value as NonNullable<components['schemas']['Assignment']['role']>}]}))}><option value="ProjectManager">Project managers</option><option value="Contributor">Contributors</option><option value="OrganizationAdmin">Organization admins</option><option value="WorkspaceAdmin">Workspace admins</option><option value="WorkspaceOwner">Workspace owners</option></select></label>
      <details><summary>Advanced recurrence, assignment and reminder properties</summary><label>Schedule definition JSON<textarea rows={12} value={source} maxLength={65536} onChange={e=>{setSource(e.target.value);setPreview(undefined);}}/></label><p>Use exact published form ID/version and eligible user, group, role or shift targets. Times are in the named timezone.</p></details><button disabled={busy}>Create schedule draft</button></form>
      <label>Schedule<select aria-label="Schedule" value={schedule} onChange={e=>setSchedule(e.target.value)}><option value="">Choose schedule</option>{schedules.map(item=><option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
      {scheduleCursor&&<button disabled={busy} onClick={()=>void run(async()=>{const result=await api.GET(schedulesPath,{params:{path,query:{...(project?{project_id:project}:{}),cursor:scheduleCursor!}}});if(result.data){setSchedules(current=>[...current,...result.data!.items]);setScheduleCursor(result.data.next_cursor);}})}>Load more schedules</button>}
      {version&&<><label>Schedule version<select value={number} onChange={e=>{const item=versions.find(v=>v.number===Number(e.target.value));if(item){setVersion(item);setNumber(item.number);setSource(JSON.stringify(item.definition,null,2));setPreview(undefined);setLifecyclePreview(false);}}}>{versions.map(item=><option key={item.id} value={item.number}>{item.number} ({item.state})</option>)}</select></label>
        <button disabled={busy||version.state!=='draft'} onClick={()=>void versionSave()}>Save schedule draft</button><button disabled={busy} onClick={()=>void clone()}>Clone schedule version</button>
        <button disabled={busy||version.state!=='draft'} onClick={()=>void activate(false)}>Preview activation</button>{preview&&<><pre>{JSON.stringify(preview.definition,null,2)}</pre><button disabled={busy} onClick={()=>void activate(true)}>Activate reviewed schedule</button></>}
        <button disabled={busy||version.state!=='active'} onClick={()=>void materialize()}>Generate next 30 days</button>
        <label>Schedule lifecycle<select value={lifecycle} onChange={e=>{setLifecycle(e.target.value as typeof lifecycle);setLifecyclePreview(false);}}><option value="paused">Pause</option><option value="active">Resume</option><option value="retired">Retire</option></select></label><label>Schedule change reason<input id="schedule-reason" maxLength={500}/></label><button disabled={busy||version.state==='draft'||version.state==='retired'} onClick={()=>void changeLifecycle(false)}>Preview schedule lifecycle</button>{lifecyclePreview&&<button disabled={busy} onClick={()=>void changeLifecycle(true)}>Apply schedule lifecycle</button>}
      </>}
      <button disabled={busy} onClick={()=>void run(async()=>{let cursor:string|null=null;let total=0;do{const body:components["schemas"]["ReminderGeneration"]={...(project?{project_id:project}:{}),cursor};const result=await api.POST(`${base}/task-reminders/generate`,{params:{path},body});if(!result.data){setMessage(failure(result.error));return;}total+=result.data.created;cursor=result.data.next_cursor;}while(cursor);setMessage(`Generated ${total} new reminders.`);})}>Generate due reminders</button>
    </details>}
  </section>;
}
