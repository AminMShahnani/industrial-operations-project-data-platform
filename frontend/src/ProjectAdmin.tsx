import { useEffect, useState, type FormEvent } from 'react';
import type { components } from './api-schema';
import type { MethodResponse } from 'openapi-fetch';
import type { apiClient } from './client';
import { FormStudio } from './FormStudio';
import { MasterDataAdmin } from './MasterDataAdmin';
import { MemberLookup } from './MemberLookup';
import { Scheduling } from './Scheduling';
import { Workflows } from './Workflows';
import { Automation } from './Automation';
import { ProjectAnnotations } from './ProjectAnnotations';

type Project = MethodResponse<ReturnType<typeof apiClient>, 'get', '/api/v1/organizations/{organization_id}/workspaces/{workspace_id}/projects/{project_id}'>;
type Group = components['schemas']['Group'];
type Client = ReturnType<typeof apiClient>;
const projectPath = '/api/v1/organizations/{organization_id}/workspaces/{workspace_id}/projects/{project_id}' as const;
const workspacePath = '/api/v1/organizations/{organization_id}/workspaces/{workspace_id}' as const;

export function ProjectAdministration({ api, organization, workspace, userId }: { api: Client; organization: string; workspace: string; userId: string }) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [selected, setSelected] = useState('');
  const [taskForm, setTaskForm] = useState<{id:string;form:string;draft:string}>();
  const [workflowSubmission,setWorkflowSubmission]=useState<string>();
  const [permissions, setPermissions] = useState<string[]>([]);
  const [projectPermissions, setProjectPermissions] = useState<string[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [groupCursor, setGroupCursor] = useState<string | null>(null);
  const [preview, setPreview] = useState<{ state: string; reason: string; version: number }>();
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [member, setMember] = useState('');
  const [selectedGroup, setSelectedGroup] = useState('');
  const [groupPermissions, setGroupPermissions] = useState<string[]>([]);
  const [groupMember, setGroupMember] = useState('');
  const [lastMembership, setLastMembership] = useState<{ kind: 'direct' | 'department'; id: string; project: string }>();
  const current = projects.find(item => item.id === selected);
  const group = groups.find(item => item.id === selectedGroup);
  const path = { organization_id: organization, workspace_id: workspace };

  useEffect(() => {
    let alive = true;
    void Promise.all([
      api.GET(`${workspacePath}/projects`, { params: { path } }),
      api.GET(`${workspacePath}/groups`, { params: { path } }),
      api.GET(`${workspacePath}/permissions`, { params: { path } }),
    ]).then(([projectResult, groupResult, permissionResult]) => {
      if (!alive) return;
      if (projectResult.data) { setProjects(projectResult.data.items); setCursor(projectResult.data.next_cursor); setSelected(projectResult.data.items[0]?.id ?? ''); }
      if (groupResult.data) { setGroups(groupResult.data.items); setGroupCursor(groupResult.data.next_cursor); setSelectedGroup(groupResult.data.items[0]?.id ?? ''); }
      if (permissionResult.data) setPermissions(permissionResult.data.permissions);
    }).catch(() => { if (alive) setMessage('Workspace administration could not be loaded.'); });
    return () => { alive = false; };
  }, [api, organization, workspace]);

  useEffect(() => {
    setPreview(undefined); setProjectPermissions([]); setMember(''); setLastMembership(undefined);
    setTaskForm(undefined);
    setWorkflowSubmission(undefined);
    if (!selected) return;
    let alive = true;
    void api.GET(`${projectPath}/permissions`, { params: { path: { ...path, project_id: selected } } }).then(result => {
      if (alive && result.data) setProjectPermissions(result.data.permissions);
    }).catch(() => { if (alive) setMessage('Project access could not be loaded.'); });
    return () => { alive = false; };
  }, [api, organization, workspace, selected]);

  useEffect(() => {
    setGroupPermissions([]); setGroupMember('');
    if (!selectedGroup) return;
    let alive = true;
    void api.GET(`${workspacePath}/groups/{group_id}/permissions`, { params: { path: { ...path, group_id: selectedGroup } } }).then(result => {
      if (alive && result.data) setGroupPermissions(result.data.permissions);
    }).catch(() => { if (alive) setMessage('Group access could not be loaded.'); });
    return () => { alive = false; };
  }, [api, organization, workspace, selectedGroup]);

  async function run(action: () => Promise<void>) {
    setBusy(true); setMessage('');
    try { await action(); } catch { setMessage('The operation could not be completed. Check your access and refresh before retrying.'); }
    finally { setBusy(false); }
  }

  async function createProject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const values = new FormData(form);
    await run(async () => {
      const result = await api.POST(`${workspacePath}/projects`, { params: { path }, body: { name: String(values.get('name')) } });
      if (!result.data) throw new Error('denied');
      setProjects(items => [...items, result.data]); setSelected(result.data.id); form.reset(); setMessage('Project created.');
    });
  }

  async function updateProject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!current) return;
    const form = new FormData(event.currentTarget);
    await run(async () => {
      const result = await api.PUT(projectPath, { params: { path: { ...path, project_id: current.id } }, body: {
        name: String(form.get('name')), expected_version: current.version,
        context: { ...current.context, description: String(form.get('description')), starts_on: String(form.get('starts')) || null, ends_on: String(form.get('ends')) || null },
      } });
      if (!result.data) throw new Error('denied');
      setProjects(items => items.map(item => item.id === result.data.id ? result.data : item)); setPreview(undefined); setMessage('Project updated.');
    });
  }

  async function transition(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!current) return;
    const form = new FormData(event.currentTarget);
    const target = { state: String(form.get('state')), reason: String(form.get('reason')), version: current.version };
    await run(async () => {
      const result = await api.POST(`${projectPath}/transitions`, { params: { path: { ...path, project_id: current.id } },
        body: { state: target.state, reason: target.reason, expected_version: target.version, dry_run: true } });
      if (!result.data) throw new Error('denied');
      setPreview(target); setMessage('Transition preview ready. Review it before applying.');
    });
  }

  async function applyTransition() {
    if (!current || !preview) return;
    await run(async () => {
      const result = await api.POST(`${projectPath}/transitions`, { params: { path: { ...path, project_id: current.id } },
        body: { state: preview.state, reason: preview.reason, expected_version: preview.version, dry_run: false } });
      if (!result.data) throw new Error('denied');
      setProjects(items => items.map(item => item.id === result.data.id ? result.data : item)); setPreview(undefined); setMessage('Project state changed.');
    });
  }

  async function createGroup(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const values = new FormData(form);
    await run(async () => {
      const result = await api.POST(`${workspacePath}/groups`, { params: { path }, body: {
        name: String(values.get('name')), kind: values.get('kind') === 'team' ? 'team' : 'department',
      } });
      if (!result.data) throw new Error('denied');
      setGroups(items => [...items, result.data]); setSelectedGroup(result.data.id); form.reset(); setMessage('Department or team created.');
    });
  }

  async function projectMember(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!current) return;
    const form = new FormData(event.currentTarget);
    const role = String(form.get('role')) as components['schemas']['ProjectRole'];
    await run(async () => {
      if (form.get('department')) {
        const result = await api.POST(`${projectPath}/department-grants`, { params: { path: { ...path, project_id: current.id } },
          body: { role, department_id: String(form.get('department')) } });
        if (!result.data) throw new Error('denied');
        setLastMembership({ kind: 'department', id: result.data.id, project: current.id }); setMessage('Department project access granted.');
      } else {
        const result = await api.POST(`${projectPath}/memberships`, { params: { path: { ...path, project_id: current.id } },
          body: { role, user_id: String(form.get('user')) } });
        if (!result.data) throw new Error('denied');
        setLastMembership({ kind: 'direct', id: result.data.id, project: current.id }); setMessage('Direct project access granted.');
      }
    });
  }

  async function revokeLastMembership() {
    if (!lastMembership) return;
    await run(async () => {
      const params = { path: { ...path, project_id: lastMembership.project } };
      const result = lastMembership.kind === 'direct' ? await api.POST(`${projectPath}/memberships/{membership_id}/revoke`, {
        params: { path: { ...params.path, membership_id: lastMembership.id } },
      }) : await api.POST(`${projectPath}/department-grants/{grant_id}/revoke`, {
        params: { path: { ...params.path, grant_id: lastMembership.id } },
      });
      if (result.error) throw new Error('denied');
      setLastMembership(undefined); setMessage('Access grant revoked. History preserved.');
    });
  }

  async function updateGroup(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!group) return;
    const values = new FormData(event.currentTarget);
    await run(async () => {
      const result = await api.PUT(`${workspacePath}/groups/{group_id}`, { params: { path: { ...path, group_id: group.id } },
        body: { name: String(values.get('name')), active: values.get('active') === 'on', expected_version: group.version } });
      if (!result.data) throw new Error('denied');
      setGroups(items => items.map(item => item.id === result.data.id ? result.data : item)); setGroupMember(''); setMessage('Group updated.');
    });
  }

  async function addGroupMember(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!group) return;
    const values = new FormData(event.currentTarget);
    await run(async () => {
      const result = await api.POST(`${workspacePath}/groups/{group_id}/memberships`, { params: { path: { ...path, group_id: group.id } },
        body: { user_id: groupMember, manager: values.get('manager') === 'on' } });
      if (!result.data) throw new Error('denied');
      setMessage('Group member added.');
    });
  }

  async function moreProjects() {
    if (!cursor) return;
    await run(async () => {
      const result = await api.GET(`${workspacePath}/projects`, { params: { path, query: { cursor } } });
      if (!result.data) throw new Error('denied');
      setProjects(items => [...items, ...result.data.items]); setCursor(result.data.next_cursor);
    });
  }

  async function moreGroups() {
    if (!groupCursor) return;
    await run(async () => {
      const result = await api.GET(`${workspacePath}/groups`, { params: { path, query: { cursor: groupCursor } } });
      if (!result.data) throw new Error('denied');
      setGroups(items => [...items, ...result.data.items]); setGroupCursor(result.data.next_cursor);
    });
  }

  return <section aria-label="Workspace administration">
    <p role="status" aria-live="polite">{message}</p>
    <h2>Projects</h2>
    <label>Project<select aria-label="Project" disabled={busy} value={selected} onChange={event => setSelected(event.target.value)}>
      <option value="">Choose a project</option>{projects.map(item => <option key={item.id} value={item.id}>{item.name} ({item.state})</option>)}
    </select></label>
    {cursor && <button disabled={busy} onClick={() => void moreProjects()}>Load more projects</button>}
    {permissions.includes('project.create') && <form onSubmit={event => void createProject(event)}>
      <label>Project name<input name="name" required maxLength={120} /></label><button disabled={busy}>Create project</button>
    </form>}
    {current && projectPermissions.includes('project.manage') && !current.lifecycle.terminal?.includes(current.state) && <div key={current.id + ':' + current.version}>
      <form onSubmit={event => void updateProject(event)}><label>Edit project name<input name="name" defaultValue={current.name} required maxLength={120} /></label>
        <label>Description<textarea name="description" defaultValue={current.context.description ?? ''} maxLength={2000} /></label>
        <label>Start date<input type="date" name="starts" defaultValue={current.context.starts_on ?? ''} /></label>
        <label>End date<input type="date" name="ends" defaultValue={current.context.ends_on ?? ''} /></label><button disabled={busy}>Save project</button>
      </form>
      <form onSubmit={event => void transition(event)}><label>Next state<select name="state" required>
        {current.lifecycle.transitions?.filter(([from]) => from === current.state).map(([, to]) => <option key={to}>{to}</option>)}
      </select></label><label>Transition reason<input name="reason" required maxLength={500} /></label><button disabled={busy}>Preview transition</button></form>
      {preview && <div><p>Review: {current.state} → {preview.state}. Reason: {preview.reason}</p><button disabled={busy} onClick={() => void applyTransition()}>Apply transition</button></div>}
    </div>}
    {current && <ProjectAnnotations key={'annotations'+organization+workspace+current.id} api={api} organization={organization} workspace={workspace} project={current.id} />}
    <h2>Departments and teams</h2>
    <ul>{groups.map(group => <li key={group.id}>{group.name} ({group.kind}, {group.active ? 'active' : 'inactive'})</li>)}</ul>
    {groupCursor && <button disabled={busy} onClick={() => void moreGroups()}>Load more departments and teams</button>}
    {permissions.includes('department.manage') && <form onSubmit={event => void createGroup(event)}>
      <label>Group name<input name="name" required maxLength={120} /></label>
      <label>Group kind<select name="kind"><option value="department">Department</option><option value="team">Team</option></select></label>
      <button disabled={busy}>Create department or team</button>
    </form>}
    <label>Manage department or team<select aria-label="Manage department or team" value={selectedGroup} disabled={busy} onChange={event => setSelectedGroup(event.target.value)}>
      <option value="">Choose a group</option>{groups.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
    </select></label>
    {group && groupPermissions.includes('group.manage') && <div key={group.id + ':' + group.version}>
      <form onSubmit={event => void updateGroup(event)}><label>Edit group name<input name="name" defaultValue={group.name} required maxLength={120} /></label>
        <label>Group active<input name="active" type="checkbox" defaultChecked={group.active} /></label>
        <p>Inactive groups stop conferring department project access. Membership history is retained.</p><button disabled={busy}>Save group</button>
      </form>
      {group.active && <form onSubmit={event => void addGroupMember(event)}>
        <MemberLookup key={group.id} api={api} organization={organization} workspace={workspace} scope={{ kind: 'group', id: group.id }} onSelect={setGroupMember} />
        <label>Group manager<input name="manager" type="checkbox" /></label><button disabled={busy || !groupMember}>Add group member</button>
      </form>}
    </div>}
    {current && projectPermissions.includes('project.members.manage') && <>
      <h3>Project access</h3><p>Department membership grants access only after an explicit project grant.</p>
      <form onSubmit={event => void projectMember(event)}>
        <MemberLookup key={current.id} api={api} organization={organization} workspace={workspace} scope={{ kind: 'project', id: current.id }} onSelect={setMember} />
        <input type="hidden" name="user" value={member} />
        <label>Direct project role<select name="role"><option>Viewer</option><option>Contributor</option><option>Reviewer</option><option>Approver</option><option>ProjectManager</option></select></label>
        <button disabled={busy || !member}>Grant direct project access</button>
      </form>
      <form onSubmit={event => void projectMember(event)}>
        <label>Department<select name="department" required><option value="">Choose a department</option>{groups.filter(group => group.active && group.kind === 'department').map(group => <option key={group.id} value={group.id}>{group.name}</option>)}</select></label>
        <label>Department project role<select name="role"><option>Viewer</option><option>Contributor</option><option>Reviewer</option><option>Approver</option><option>ProjectManager</option></select></label>
        <button disabled={busy}>Grant department project access</button>
      </form>
      {lastMembership && <button disabled={busy} onClick={() => void revokeLastMembership()}>Revoke the last access grant</button>}
    </>}
    <Scheduling key={'work'+organization+workspace+selected} api={api} organization={organization} workspace={workspace} project={selected}
      userId={userId} canManage={selected?projectPermissions.includes('schedule.manage'):permissions.includes('schedule.manage')} onOpen={task=>{if(task.submission_id&&task.form_id)setTaskForm({id:task.id,form:task.form_id,draft:task.submission_id});}} />
    <Workflows key={'workflow'+organization+workspace+selected} api={api} organization={organization} workspace={workspace} project={selected}
      canManage={selected?projectPermissions.includes('workflow.manage'):permissions.includes('workflow.manage')} submission={workflowSubmission} onOpenRevision={row=>setTaskForm({id:row.id,form:row.form_id,draft:row.id})}/>
    <FormStudio key={'forms' + organization + workspace + selected + (taskForm?.id??'')} api={api} organization={organization} workspace={workspace} project={selected}
      canManage={selected ? projectPermissions.includes('form.manage') : permissions.includes('form.manage')} canManageLibrary={permissions.includes('form.manage')} taskForm={taskForm?.form} taskDraft={taskForm?.draft} onSubmitted={setWorkflowSubmission}/>
    {(selected ? projectPermissions : permissions).includes('automation.manage') && <Automation key={'automation'+organization+workspace+selected} api={api} organization={organization} workspace={workspace} project={selected}/>}
    <MasterDataAdmin key={organization + workspace + selected} api={api} organization={organization} workspace={workspace} project={selected}
      canManage={selected ? projectPermissions.includes('master_data.manage') : permissions.includes('master_data.manage')} />
  </section>;
}
