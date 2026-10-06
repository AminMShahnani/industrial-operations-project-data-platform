import { useEffect, useRef, useState, type FormEvent } from 'react';
import type { components } from './api-schema';
import type { apiClient } from './client';
import { approvalWorkflow, parseWorkflowDefinition } from './workflow-definition';

type Client=ReturnType<typeof apiClient>;
type Workflow=components['schemas']['Workflow'];
type Version=components['schemas']['WorkflowVersion'];
type History=components['schemas']['WorkflowHistory'];
type Submission=components['schemas']['Submission'];
type Action=components['schemas']['ActionCommand']['kind'];
const base='/api/v1/organizations/{organization_id}/workspaces/{workspace_id}' as const;
const versionPath=`${base}/workflows/{workflow_id}/versions/{number}` as const;
function failure(error:unknown):string {return error && typeof error==='object' && 'code' in error?String(error.code):'Request could not be completed.';}

export function Workflows({api,organization,workspace,project,canManage,submission,onOpenRevision}:{api:Client;organization:string;workspace:string;project:string;canManage:boolean;submission?:string|undefined;onOpenRevision:(row:Submission)=>void}) {
  const path={organization_id:organization,workspace_id:workspace};
  const [inbox,setInbox]=useState<components['schemas']['WorkflowInstance'][]>([]);
  const [cursor,setCursor]=useState<string|null>(null);
  const [history,setHistory]=useState<History>();
  const [evidence,setEvidence]=useState<Submission>();
  const [attachmentIds,setAttachmentIds]=useState<string[]>([]);
  const [workflows,setWorkflows]=useState<Workflow[]>([]);
  const [workflowCursor,setWorkflowCursor]=useState<string|null>(null);
  const [selected,setSelected]=useState('');
  const [versions,setVersions]=useState<Version[]>([]);
  const [version,setVersion]=useState<Version>();
  const [versionCursor,setVersionCursor]=useState<string|null>(null);
  const [forms,setForms]=useState<components['schemas']['Form'][]>([]);
  const [formCursor,setFormCursor]=useState<string|null>(null);
  const [form,setForm]=useState('');
  const [formVersions,setFormVersions]=useState<components['schemas']['FormVersion'][]>([]);
  const [formNumber,setFormNumber]=useState(1);
  const [candidates,setCandidates]=useState<components['schemas']['User'][]>([]);
  const [recipients,setRecipients]=useState<components['schemas']['User'][]>([]);
  const [mode,setMode]=useState<'one'|'all'|'quorum'|'sequential'>('one');
  const [quorum,setQuorum]=useState(1);
  const [definition,setDefinition]=useState('');
  const [preview,setPreview]=useState<Version>();
  const [reason,setReason]=useState('');
  const [busy,setBusy]=useState(false);
  const [message,setMessage]=useState('');
  const pending=useRef<{kind:Action;reason:string;revision:number;key:string}|undefined>(undefined);
  const revisionPending=useRef<{instance:string;reason:string;key:string}|undefined>(undefined);
  const generation=useRef(0);

  async function run(work:()=>Promise<void>) {setBusy(true);setMessage('');try {await work();} catch(error){setMessage(error instanceof Error?error.message:failure(error));} finally {setBusy(false);}}
  async function refreshInbox(after?:string) {
    const result=await api.GET(`${base}/workflow-inbox`,{params:{path,query:{project_id:project||null,cursor:after??null}}});
    if (!result.data) throw new Error(failure(result.error));
    setInbox(current=>after?[...current,...result.data.items]:result.data.items);setCursor(result.data.next_cursor??null);
  }
  async function loadEvidence(row:History,ticket=generation.current) {
    setAttachmentIds([]);
    const result=await api.GET(`${base}/submissions/{submission_id}`,{params:{path:{...path,submission_id:row.instance.submission_id}}});
    if(ticket!==generation.current)return;
    setEvidence(result.data);if (!result.data) {setMessage(failure(result.error));return;}
    const record=result.data;
    const formResult=await api.GET(`${base}/forms/{form_id}/versions/{number}`,{params:{path:{...path,form_id:record.form_id,number:record.form_number}}});
    if(ticket!==generation.current)return;
    if(formResult.data){const ids:string[]=[];const collect=(fields:components['schemas']['Component-Output'][],values:Record<string,unknown>)=>{for(const field of fields){const value=values[field.key];if((field.kind==='file'||field.kind==='image')&&typeof value==='string')ids.push(value);if(field.children&&Array.isArray(value))for(const item of value)if(item&&typeof item==='object'&&!Array.isArray(item))collect(field.children,item as Record<string,unknown>);}};for(const section of formResult.data.definition.sections)collect(section.components??[],record.values.fields??{});setAttachmentIds(ids);}
  }
  async function loadHistory(id:string) {
    const ticket=++generation.current;
    setEvidence(undefined);setHistory(undefined);
    const result=await api.GET(`${base}/workflow-instances/{instance_id}`,{params:{path:{...path,instance_id:id}}});
    if (ticket!==generation.current) return;
    if (!result.data) throw new Error(failure(result.error));
    setHistory(result.data);setEvidence(undefined);pending.current=undefined;revisionPending.current=undefined;setReason('');await loadEvidence(result.data,ticket);
  }
  async function loadVersions(id:string,after?:string) {
    const result=await api.GET(`${base}/workflows/{workflow_id}/versions`,{params:{path:{...path,workflow_id:id},query:{cursor:after??null}}});
    if (!result.data) throw new Error(failure(result.error));
    setVersions(current=>after?[...current,...result.data.items]:result.data.items);setVersionCursor(result.data.next_cursor??null);
    if (!after) {const first=result.data.items[0];setVersion(first);setDefinition(first?JSON.stringify(first.definition,null,2):'');setPreview(undefined);}
  }
  async function refreshWorkflows(after?:string) {
    const result=await api.GET(`${base}/workflows`,{params:{path,query:{project_id:project||null,cursor:after??null}}});
    if (!result.data) throw new Error(failure(result.error));
    setWorkflows(current=>after?[...current,...result.data.items]:result.data.items);setWorkflowCursor(result.data.next_cursor??null);
  }
  async function loadForms(after?:string) {
    const result=await api.GET(`${base}/forms`,{params:{path,query:{project_id:project||null,cursor:after??null}}});
    if (!result.data) throw new Error(failure(result.error));
    setForms(current=>after?[...current,...result.data.items]:result.data.items);setFormCursor(result.data.next_cursor);
  }
  useEffect(()=>{
    let alive=true;setBusy(true);
    void Promise.all([api.GET(`${base}/workflow-inbox`,{params:{path,query:{project_id:project||null}}}),...(canManage?[api.GET(`${base}/workflows`,{params:{path,query:{project_id:project||null}}}),api.GET(`${base}/forms`,{params:{path,query:{project_id:project||null}}})]:[])]).then(results=>{
      if (!alive)return;
      const inboxResult=results[0];if(inboxResult?.data && 'items' in inboxResult.data){setInbox(inboxResult.data.items as components['schemas']['WorkflowInstance'][]);setCursor(inboxResult.data.next_cursor??null);}
      const workflowResult=results[1];if(workflowResult?.data && 'items' in workflowResult.data){setWorkflows(workflowResult.data.items as Workflow[]);setWorkflowCursor(workflowResult.data.next_cursor??null);}
      const formResult=results[2];if(formResult?.data && 'items' in formResult.data){setForms(formResult.data.items as components['schemas']['Form'][]);setFormCursor(formResult.data.next_cursor??null);}
    }).catch(()=>{if(alive)setMessage('Workflow inbox could not be loaded.');}).finally(()=>{if(alive)setBusy(false);});
    return()=>{alive=false;generation.current++;};
  },[api,organization,workspace,project,canManage]);
  useEffect(()=>{
    if(!form){setFormVersions([]);return;}let alive=true;
    void api.GET(`${base}/forms/{form_id}/versions`,{params:{path:{...path,form_id:form}}}).then(result=>{if(alive&&result.data){const published=result.data.items.filter(item=>item.state==='published');setFormVersions(published);setFormNumber(published[0]?.number??1);}});
    return()=>{alive=false;};
  },[api,organization,workspace,form]);
  useEffect(()=>{
    if(!submission)return;let alive=true;const ticket=++generation.current;setBusy(true);setHistory(undefined);setEvidence(undefined);
    void api.GET(`${base}/submissions/{submission_id}/workflow`,{params:{path:{...path,submission_id:submission}}}).then(async result=>{if(alive&&ticket===generation.current&&result.data){setHistory(result.data);await loadEvidence(result.data,ticket);}}).catch(()=>{if(alive)setMessage('Workflow history could not be loaded.');}).finally(()=>{if(alive&&ticket===generation.current)setBusy(false);});
    return()=>{alive=false;};
  },[api,organization,workspace,submission]);

  async function findApprover(event:FormEvent<HTMLFormElement>) {
    event.preventDefault();const email=String(new FormData(event.currentTarget).get('email'));
    await run(async()=>{const result=await api.GET(`${base}/workflow-assignment-candidates`,{params:{path,query:{email,project_id:project||null}}});if(!result.data)throw new Error(failure(result.error));setCandidates(result.data.items);setMessage(result.data.items.length?'Choose the approver to add.':'No eligible approver matches that email in this scope.');});
  }
  async function create(event:FormEvent<HTMLFormElement>) {
    event.preventDefault();const name=String(new FormData(event.currentTarget).get('name'));
    await run(async()=>{const body=approvalWorkflow(form,formNumber,recipients.map(user=>user.id),mode,quorum);const result=await api.POST(`${base}/workflows`,{params:{path},body:{name,project_id:project||null,definition:body}});if(!result.data)throw new Error(failure(result.error));setSelected(result.data.id);await refreshWorkflows();await loadVersions(result.data.id);setMessage('Workflow draft created. Review and activate it before use.');});
  }
  async function save() {
    if(!version)return;await run(async()=>{const result=await api.PUT(versionPath,{params:{path:{...path,workflow_id:selected,number:version.number}},body:{expected_revision:version.revision,definition:parseWorkflowDefinition(definition)}});if(!result.data)throw new Error(failure(result.error));setVersion(result.data);setDefinition(JSON.stringify(result.data.definition,null,2));setPreview(undefined);setVersions(current=>current.map(item=>item.id===result.data.id?result.data:item));setMessage('Workflow draft saved.');});
  }
  async function activate(apply:boolean) {
    if(!version)return;await run(async()=>{const result=await api.POST(`${versionPath}/activate`,{params:{path:{...path,workflow_id:selected,number:version.number}},body:{expected_revision:version.revision,dry_run:!apply,expected_sha256:apply?preview?.content_sha256??null:null}});if(!result.data)throw new Error(failure(result.error));if(apply){setVersion(result.data);setPreview(undefined);await refreshWorkflows();await loadVersions(selected);setMessage('Workflow activated for its published form version.');}else{setPreview(result.data);setMessage('Activation validated. Review the form and assignments before applying.');}});
  }
  async function clone(event:FormEvent<HTMLFormElement>) {
    event.preventDefault();if(!version)return;const number=Number(new FormData(event.currentTarget).get('number'));
    await run(async()=>{const result=await api.POST(`${base}/workflows/{workflow_id}/versions`,{params:{path:{...path,workflow_id:selected}},body:{source_number:version.number,number}});if(!result.data)throw new Error(failure(result.error));await loadVersions(selected);setVersion(result.data);setDefinition(JSON.stringify(result.data.definition,null,2));setPreview(undefined);setMessage('New workflow version created; historical instances retain their original version.');});
  }
  async function decide(kind:Action) {
    if(!history)return;await run(async()=>{const row=history.instance;if(!pending.current||pending.current.kind!==kind||pending.current.reason!==reason||pending.current.revision!==row.revision)pending.current={kind,reason,revision:row.revision,key:crypto.randomUUID()};const result=await api.POST(`${base}/workflow-instances/{instance_id}/actions`,{params:{path:{...path,instance_id:row.id}},body:{expected_revision:row.revision,idempotency_key:pending.current.key,kind,reason}});if(!result.data)throw new Error(failure(result.error));await loadHistory(row.id);await refreshInbox();setMessage(`Workflow action recorded: ${kind}.`);});
  }
  async function revise() {
    if(!history)return;await run(async()=>{const row=history.instance;if(!revisionPending.current||revisionPending.current.instance!==row.id||revisionPending.current.reason!==reason)revisionPending.current={instance:row.id,reason,key:crypto.randomUUID()};const result=await api.POST(`${base}/workflow-instances/{instance_id}/revisions`,{params:{path:{...path,instance_id:row.id}},body:{expected_revision:row.revision,idempotency_key:revisionPending.current.key,reason}});if(!result.data)throw new Error(failure(result.error));onOpenRevision(result.data);await loadHistory(row.id);setMessage('Revision draft created. Supply fresh acknowledgements and attachments before resubmitting.');});
  }
  async function openRevision(id:string) {
    await run(async()=>{const result=await api.GET(`${base}/submissions/{submission_id}`,{params:{path:{...path,submission_id:id}}});if(!result.data)throw new Error(failure(result.error));onOpenRevision(result.data);});
  }
  async function download(id:string) {
    await run(async()=>{const result=await api.POST(`${base}/files/{file_id}/download`,{params:{path:{...path,file_id:id}}});if(!result.data)throw new Error(failure(result.error));const link=document.createElement('a');link.href=result.data.url;link.rel='noreferrer';link.download='';link.click();});
  }
  async function moreHistory(kind:'steps'|'actions') {
    if(!history)return;await run(async()=>{const result=await api.GET(`${base}/workflow-instances/{instance_id}`,{params:{path:{...path,instance_id:history.instance.id},query:{step_cursor:kind==='steps'?history.next_step_cursor??null:null,action_cursor:kind==='actions'?history.next_action_cursor??null:null}}});if(!result.data)throw new Error(failure(result.error));const next=result.data;setHistory(current=>current&&current.instance.id===next.instance.id?{...next,steps:kind==='steps'?[...current.steps,...next.steps]:current.steps,actions:kind==='actions'?[...current.actions,...next.actions]:current.actions,next_step_cursor:(kind==='steps'?next.next_step_cursor:current.next_step_cursor)??null,next_action_cursor:(kind==='actions'?next.next_action_cursor:current.next_action_cursor)??null}:next);});
  }
  const dirty=version&&definition!==JSON.stringify(version.definition,null,2);

  return <section aria-label="Workflow review and approval"><h2>Review and approval</h2><p role="status">{message}</p>
    <button disabled={busy} onClick={()=>void run(()=>refreshInbox())}>Refresh review inbox</button>
    <ul>{inbox.map(row=><li key={row.id}>Record {row.submission_id} · {row.current_node}<button disabled={busy} onClick={()=>void run(()=>loadHistory(row.id))}>Review record</button></li>)}</ul>
    {!inbox.length&&<p>No assigned review actions in this scope.</p>}
    {cursor&&<button disabled={busy} onClick={()=>void run(()=>refreshInbox(cursor))}>More review actions</button>}
    {history&&<article aria-label="Workflow record history"><h3>Record {history.instance.submission_id}</h3><p>Workflow version {history.instance.workflow_number} · {history.instance.state}</p>
      <button disabled={busy} onClick={()=>void run(()=>loadHistory(history.instance.id))}>Refresh record history</button>
      {evidence&&<dl>{Object.entries(evidence.values.fields??{}).map(([key,value])=><div key={key}><dt>{key}</dt><dd>{typeof value==='object'?JSON.stringify(value):String(value??'')}</dd></div>)}</dl>}
      {attachmentIds.map((id,index)=><button key={id} disabled={busy} onClick={()=>void download(id)}>Download review attachment {index+1}</button>)}
      {evidence?.signatures?.map(signature=><p key={signature.key}>Acknowledged by {signature.signer_id} at {signature.occurred_at} · {signature.reason}</p>)}
      <label>Decision reason<textarea value={reason} onChange={event=>setReason(event.target.value)} maxLength={2000}/></label>
      {history.available_actions.map(kind=><button key={kind} disabled={busy||!reason.trim()} onClick={()=>void decide(kind)}>{kind==='approve'?'Approve record':kind==='review'?'Complete review':kind==='return'?'Return for correction':'Reject record'}</button>)}
      {history.available_revision&&<button disabled={busy||!reason.trim()} onClick={()=>void revise()}>{history.available_revision==='correction'?'Create correction draft':'Create amendment draft'}</button>}
      {history.revision&&<button disabled={busy} onClick={()=>void openRevision(history.revision!.submission_id)}>Open revision draft</button>}
      {history.parent&&<button disabled={busy} onClick={()=>void run(()=>loadHistory(history.parent!.source_instance_id))}>View preceding record history</button>}
      <ol>{history.actions.map(action=><li key={action.id}>{action.kind} · {action.actor_id} · <time dateTime={action.occurred_at}>{action.occurred_at}</time> · {action.reason}</li>)}</ol>
      {history.next_action_cursor&&<button disabled={busy} onClick={()=>void moreHistory('actions')}>More workflow actions</button>}
      <ol>{history.steps.map(step=><li key={step.id}>Visit {step.number} · {step.node_key} · {step.state}</li>)}</ol>
      {history.next_step_cursor&&<button disabled={busy} onClick={()=>void moreHistory('steps')}>More workflow visits</button>}
    </article>}
    {canManage&&<details><summary>Workflow administration</summary>
      <button disabled={busy} onClick={()=>void run(()=>loadForms())}>Refresh forms for workflow</button>
      <form onSubmit={event=>void findApprover(event)}><label>Approver email<input name="email" type="email" required/></label><button disabled={busy}>Find eligible approvers</button></form>
      {candidates.map(user=><button key={user.id} disabled={busy||recipients.some(item=>item.id===user.id)} onClick={()=>setRecipients(current=>[...current,user])}>Add approver {user.email??user.id}</button>)}
      <ol>{recipients.map(user=><li key={user.id}>{user.email??user.id}<button disabled={busy} onClick={()=>setRecipients(current=>current.filter(item=>item.id!==user.id))}>Remove approver</button></li>)}</ol>
      <form onSubmit={event=>void create(event)}><label>Workflow name<input name="name" required maxLength={120}/></label>
        <label>Published form<select aria-label="Published form" value={form} onChange={event=>{setFormVersions([]);setForm(event.target.value);}} required><option value="">Choose a form</option>{forms.map(item=><option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <label>Published form version<select aria-label="Published form version" value={formNumber} onChange={event=>setFormNumber(Number(event.target.value))}>{formVersions.map(item=><option key={item.id} value={item.number}>{item.number}</option>)}</select></label>
        <label>Approval policy<select value={mode} onChange={event=>setMode(event.target.value as typeof mode)}><option value="one">One approver</option><option value="all">All approvers</option><option value="quorum">Quorum</option><option value="sequential">Sequential approvers</option></select></label>
        {mode==='quorum'&&<label>Required approvals<input type="number" min={1} max={recipients.length||1} value={quorum} onChange={event=>setQuorum(Number(event.target.value))}/></label>}
        <p>Approval always requires an independent approver. Sequential policies follow the order above.</p><button disabled={busy||!formVersions.length||!recipients.length}>Create workflow draft</button>
      </form>
      {formCursor&&<button disabled={busy} onClick={()=>void run(()=>loadForms(formCursor))}>More forms for workflow</button>}
      <label>Workflow<select value={selected} disabled={busy} onChange={event=>{const id=event.target.value;setSelected(id);if(id)void run(()=>loadVersions(id));else setVersion(undefined);}}><option value="">Choose a workflow</option>{workflows.map(row=><option key={row.id} value={row.id}>{row.name}</option>)}</select></label>
      {workflowCursor&&<button disabled={busy} onClick={()=>void run(()=>refreshWorkflows(workflowCursor))}>More workflows</button>}
      {selected&&<label>Workflow version<select aria-label="Workflow version" value={version?.number??''} disabled={busy} onChange={event=>{const row=versions.find(row=>row.number===Number(event.target.value));setVersion(row);setDefinition(row?JSON.stringify(row.definition,null,2):'');setPreview(undefined);}}>{versions.map(row=><option key={row.id} value={row.number}>{row.number} · {row.state}</option>)}</select></label>}
      {versionCursor&&<button disabled={busy} onClick={()=>void run(()=>loadVersions(selected,versionCursor))}>More workflow versions</button>}
      {version&&<><details><summary>Advanced workflow definition</summary><label>Workflow definition<textarea value={definition} disabled={busy||version.state!=='draft'} onChange={event=>{setDefinition(event.target.value);setPreview(undefined);}} rows={12}/></label></details>
        {version.state==='draft'&&<><button disabled={busy} onClick={()=>void save()}>Save workflow definition</button><button disabled={busy||Boolean(dirty)} onClick={()=>void activate(false)}>Preview workflow activation</button>{preview&&<button disabled={busy||Boolean(dirty)} onClick={()=>void activate(true)}>Apply workflow activation</button>}</>}
        <form onSubmit={event=>void clone(event)}><label>New workflow version<input name="number" type="number" min={1} required defaultValue={version.number+1}/></label><button disabled={busy}>Create new workflow version</button></form>
      </>}
    </details>}
  </section>;
}
