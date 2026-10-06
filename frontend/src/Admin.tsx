import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { useAuth } from 'react-oidc-context';
import { apiClient } from './client';
import type { components } from './api-schema';
import { ProjectAdministration } from './ProjectAdmin';

type Me = components['schemas']['Me'];
type Workspace = components['schemas']['Workspace'];
type Role = components['schemas']['Role'];

export function Administration() {
  const auth = useAuth();
  const token = auth.user?.access_token ?? '';
  const api = useMemo(() => apiClient(import.meta.env.VITE_API_URL ?? 'http://127.0.0.1:8000', token), [token]);
  const [me, setMe] = useState<Me>();
  const [organization, setOrganization] = useState('');
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [workspace, setWorkspace] = useState('');
  const [cursor, setCursor] = useState<string | null>(null);
  const [message, setMessage] = useState('');
  const [invitation, setInvitation] = useState('');
  const [busy, setBusy] = useState(false);
  const permissions = me?.memberships.find(item => item.organization_id === organization)?.permissions ?? [];

  useEffect(() => {
    if (!auth.isAuthenticated || !token) return;
    let current = true;
    void api.GET('/api/v1/me').then(result => {
      if (!current) return;
      if (result.data) {
        setMe(result.data);
        setOrganization(result.data.memberships[0]?.organization_id ?? '');
      } else setMessage('Your organization access could not be loaded.');
    }).catch(() => { if (current) setMessage('The platform could not be reached.'); });
    return () => { current = false; };
  }, [api, auth.isAuthenticated, token]);

  useEffect(() => {
    setWorkspaces([]); setWorkspace(''); setInvitation(''); setCursor(null);
    if (!organization || !auth.isAuthenticated) return;
    let current = true;
    void api.GET('/api/v1/organizations/{organization_id}/workspaces', {
      params: { path: { organization_id: organization } },
    }).then(result => {
      if (!current) return;
      if (result.data) {
        setWorkspaces(result.data.items); setCursor(result.data.next_cursor);
        setWorkspace(result.data.items[0]?.id ?? '');
      } else setMessage('This organization is unavailable or your access has changed.');
    }).catch(() => { if (current) setMessage('Workspaces could not be loaded.'); });
    return () => { current = false; };
  }, [api, organization, auth.isAuthenticated]);

  async function createWorkspace(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setMessage('');
    const form = event.currentTarget;
    try {
      const result = await api.POST('/api/v1/organizations/{organization_id}/workspaces', {
        params: { path: { organization_id: organization } },
        body: { name: String(new FormData(form).get('name')) },
      });
      if (result.data) {
        setWorkspaces(items => [...items, result.data]); setWorkspace(result.data.id);
        setMessage('Workspace created.'); form.reset();
      } else setMessage('Workspace could not be created. Check your access and try again.');
    } catch { setMessage('The platform could not be reached.'); }
    finally { setBusy(false); }
  }

  async function createInvitation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setInvitation(''); setMessage('');
    const form = new FormData(event.currentTarget);
    try {
      const result = await api.POST('/api/v1/organizations/{organization_id}/invitations', {
        params: { path: { organization_id: organization } },
        body: { email: String(form.get('email')), role: String(form.get('role')) as Role,
                scope_type: 'workspace', scope_id: workspace },
      });
      if (result.data) { setInvitation(result.data.token); setMessage('Invitation created for this workspace.'); }
      else setMessage('Invitation could not be created. Check your access and selected role.');
    } catch { setMessage('The platform could not be reached.'); }
    finally { setBusy(false); }
  }

  async function acceptInvitation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setMessage('');
    const form = new FormData(event.currentTarget);
    try {
      const result = await api.POST('/api/v1/organizations/{organization_id}/invitations/accept', {
        params: { path: { organization_id: String(form.get('organization')) } },
        body: { token: String(form.get('token')) },
      });
      if (result.data) {
        const refreshed = await api.GET('/api/v1/me');
        if (refreshed.data) { setMe(refreshed.data); setOrganization(String(form.get('organization'))); }
        setMessage('Invitation accepted.');
      } else setMessage('Invitation unavailable. Check the code, organization and verified sign-in email.');
    } catch { setMessage('The platform could not be reached.'); }
    finally { setBusy(false); }
  }

  async function loadMore() {
    if (!cursor) return;
    setBusy(true);
    try {
      const result = await api.GET('/api/v1/organizations/{organization_id}/workspaces', {
        params: { path: { organization_id: organization }, query: { cursor } },
      });
      if (result.data) { setWorkspaces(items => [...items, ...result.data.items]); setCursor(result.data.next_cursor); }
      else setMessage('More workspaces could not be loaded.');
    } catch { setMessage('The platform could not be reached.'); }
    finally { setBusy(false); }
  }

  if (auth.isLoading) return <p role="status">Connecting to your identity provider…</p>;
  if (auth.error) return <p role="alert">Sign-in could not be completed. Please try again.</p>;
  if (!auth.isAuthenticated || auth.user?.expired) {
    return <section><h2>Sign in to your organization</h2>
      <p>Use your organization’s identity provider to access your workspaces.</p>
      <button onClick={() => void auth.signinRedirect().catch(() => setMessage('Sign-in is unavailable.'))}>Sign in</button>
      <p role="status">{message}</p></section>;
  }
  return <>
    <div className="toolbar"><p>Signed in to your organization</p>
      <button onClick={() => { setMe(undefined); setWorkspaces([]); setInvitation(''); void auth.removeUser(); }}>Sign out here</button></div>
    <p role="status" aria-live="polite">{message}</p>
    <section><h2>Organization and workspace</h2>
      <label>Organization<select aria-label="Organization" value={organization} onChange={event => setOrganization(event.target.value)}>
        <option value="">Choose an organization</option>
        {me?.memberships.map(item => <option key={item.organization_id} value={item.organization_id}>{item.organization_name}</option>)}
      </select></label>
      <label>Workspace<select aria-label="Workspace" value={workspace} onChange={event => { setWorkspace(event.target.value); setInvitation(''); }}>
        <option value="">Choose a workspace</option>
        {workspaces.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
      </select></label>
      {cursor && <button disabled={busy} onClick={() => void loadMore()}>Load more workspaces</button>}
      {permissions.includes('workspace.create') && <form onSubmit={event => void createWorkspace(event)}>
        <label>Workspace name<input name="name" required maxLength={120} /></label>
        <button disabled={busy}>Create workspace</button>
      </form>}
    </section>
    {permissions.includes('iam.grants.manage') && workspace && <section><h2>Invite a workspace member</h2>
      <p>Review the selected organization and workspace before creating access.</p>
      <form onSubmit={event => void createInvitation(event)}>
        <label>Email<input type="email" name="email" required /></label>
        <label>Role<select name="role"><option>Viewer</option><option>Contributor</option><option>Reviewer</option><option>Approver</option><option>WorkspaceAdmin</option><option>WorkspaceOwner</option></select></label>
        <button disabled={busy}>Create invitation</button>
      </form>
      {invitation && <div><p>Share this code and organization ID with the intended member. The code expires in seven days.</p>
        <label>Invitation code<textarea readOnly value={invitation} /></label></div>}
    </section>}
    {organization && workspace && <ProjectAdministration key={organization + workspace} api={api} organization={organization} workspace={workspace} />}
    <section><h2>Accept an invitation</h2><form onSubmit={event => void acceptInvitation(event)}>
      <label>Organization ID<input name="organization" required /></label>
      <label>Invitation code<input name="token" type="password" autoComplete="off" required /></label>
      <button disabled={busy}>Accept invitation</button>
    </form></section>
  </>;
}
