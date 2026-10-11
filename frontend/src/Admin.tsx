import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import { useAuth } from 'react-oidc-context';
import { apiClient } from './client';
import type { components } from './api-schema';
import { ProjectAdministration } from './ProjectAdmin';
import { Notifications } from './Notifications';
import { EmailRecovery } from './EmailRecovery';
import { WebhookEndpoints } from './WebhookEndpoints';
import { WebhookRecovery } from './WebhookRecovery';
import { InvitationAcceptance } from './InvitationAcceptance';
import { invitationPath, invitationRequestId, invitationTargetFromState, readInvitationTarget } from './invitation-link';

type Me = components['schemas']['Me'];
type Workspace = components['schemas']['Workspace'];
type Role = components['schemas']['Role'];
type ReportColumn = components['schemas']['SavedReportDefinition']['columns'][number];

const reportColumnChoices: { value: ReportColumn; label: string }[] = [
  { value: 'id', label: 'Task ID' },
  { value: 'project_id', label: 'Project ID' },
  { value: 'kind', label: 'Task type' },
  { value: 'name', label: 'Task name' },
  { value: 'state', label: 'Status' },
  { value: 'due_at', label: 'Due date' },
];

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
  const [invitationLink, setInvitationLink] = useState('');
  const invitationRequest = useRef<{ fingerprint: string; id: string } | undefined>(undefined);
  const [busy, setBusy] = useState(false);
  const [acceptance, setAcceptance] = useState('token');
  const [emailDelivery, setEmailDelivery] = useState(false);
  const [overdue, setOverdue] = useState<components['schemas']['OverdueTaskRow'][]>([]);
  const [overdueScope, setOverdueScope] = useState<'personal' | 'aggregate'>('personal');
  const [overdueCursor, setOverdueCursor] = useState<string | null>(null);
  const [overdueMessage, setOverdueMessage] = useState('');
  const [savedReports, setSavedReports] = useState<components['schemas']['SavedReport'][]>([]);
  const [savedMessage, setSavedMessage] = useState('');
  const [savedResults, setSavedResults] = useState<components['schemas']['OverdueTaskPage'] | null>(null);
  const [exportJobs, setExportJobs] = useState<components['schemas']['ReportExportJob'][]>([]);
  const [editingReport, setEditingReport] = useState<components['schemas']['SavedReport'] | null>(null);
  const [reportName, setReportName] = useState('');
  const [reportState, setReportState] = useState('');
  const [reportSortDirection, setReportSortDirection] = useState<components['schemas']['SavedReportDefinition']['sort_direction']>('asc');
  const [reportGroupBy, setReportGroupBy] = useState<components['schemas']['SavedReportDefinition']['group_by']>('none');
  const [reportColumns, setReportColumns] = useState<ReportColumn[]>(reportColumnChoices.map(item => item.value));
  const [dashboards, setDashboards] = useState<components['schemas']['Dashboard'][]>([]);
  const [dashboardMessage, setDashboardMessage] = useState('');
  const [dashboardResults, setDashboardResults] = useState<components['schemas']['DashboardResult'][]>([]);
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
    setWorkspaces([]); setWorkspace(''); setInvitation(''); setInvitationLink(''); setCursor(null);
    setEmailDelivery(false); setAcceptance('token');
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

  useEffect(() => {
    setOverdue([]); setOverdueCursor(null); setOverdueMessage('');
    if (!organization || !workspace || !auth.isAuthenticated) return;
    let current = true;
    void api.GET('/api/v1/organizations/{organization_id}/workspaces/{workspace_id}/reports/overdue-tasks', {
      params: { path: { organization_id: organization, workspace_id: workspace }, query: { scope: overdueScope } },
    }).then(result => {
      if (!current) return;
      if (result.data) { setOverdue(result.data.items); setOverdueCursor(result.data.next_cursor); }
      else setOverdueMessage('Overdue tasks could not be loaded. Check your access and try again.');
    }).catch(() => { if (current) setOverdueMessage('The overdue task report could not be reached.'); });
    return () => { current = false; };
  }, [api, organization, workspace, overdueScope, auth.isAuthenticated]);

  useEffect(() => {
    setSavedReports([]); setSavedMessage(''); setSavedResults(null); setEditingReport(null);
    setReportName(''); setReportState(''); setReportSortDirection('asc'); setReportGroupBy('none');
    setReportColumns(reportColumnChoices.map(item => item.value));
    setDashboards([]); setDashboardMessage(''); setDashboardResults([]); setExportJobs([]);
    if (!organization || !workspace || !auth.isAuthenticated) return;
    let current = true;
    void api.GET('/api/v1/organizations/{organization_id}/workspaces/{workspace_id}/reports/saved', {
      params: { path: { organization_id: organization, workspace_id: workspace } },
    }).then(result => {
      if (!current) return;
      if (result.data) setSavedReports(result.data.items);
      else setSavedMessage('Your saved reports could not be loaded.');
    }).catch(() => { if (current) setSavedMessage('The saved report service could not be reached.'); });
    void api.GET('/api/v1/organizations/{organization_id}/workspaces/{workspace_id}/reports/dashboards', {
      params: { path: { organization_id: organization, workspace_id: workspace } },
    }).then(result => {
      if (!current) return;
      if (result.data) setDashboards(result.data.items);
      else setDashboardMessage('Your dashboards could not be loaded.');
    }).catch(() => { if (current) setDashboardMessage('The dashboard service could not be reached.'); });
    void api.GET('/api/v1/organizations/{organization_id}/workspaces/{workspace_id}/reports/export-jobs', {
      params: { path: { organization_id: organization, workspace_id: workspace } },
    }).then(result => { if (current && result.data) setExportJobs(result.data); });
    return () => { current = false; };
  }, [api, organization, workspace, auth.isAuthenticated]);

  useEffect(() => {
    if (!organization || !workspace || !exportJobs.some(job => job.state === 'pending' || job.state === 'running')) return;
    const timer = window.setInterval(() => {
      void api.GET('/api/v1/organizations/{organization_id}/workspaces/{workspace_id}/reports/export-jobs', {
        params: { path: { organization_id: organization, workspace_id: workspace } },
      }).then(result => { if (result.data) setExportJobs(result.data); });
    }, 5000);
    return () => window.clearInterval(timer);
  }, [api, organization, workspace, exportJobs]);

  async function createSavedReport(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!organization || !workspace) return;
    if (reportColumns.length === 0) { setSavedMessage('Select at least one report column.'); return; }
    const filters: components['schemas']['SavedReportDefinition']['filters'] = reportState
      ? [{ field: 'state', operator: 'eq', value: reportState as components['schemas']['StateFilter']['value'] }]
      : [];
    setBusy(true); setSavedMessage('');
    try {
      const body = {
        name: reportName,
        definition: {
          dataset: 'overdue_tasks' as const, scope: overdueScope,
          columns: reportColumns,
          filters, sort_by: 'id' as const, sort_direction: reportSortDirection, group_by: reportGroupBy,
        },
      };
      const result = editingReport
        ? await api.PUT('/api/v1/organizations/{organization_id}/workspaces/{workspace_id}/reports/saved/{report_id}', {
          params: { path: { organization_id: organization, workspace_id: workspace, report_id: editingReport.id } },
          body: { ...body, expected_version: editingReport.version },
        })
        : await api.POST('/api/v1/organizations/{organization_id}/workspaces/{workspace_id}/reports/saved', {
          params: { path: { organization_id: organization, workspace_id: workspace } }, body,
        });
      if (result.data) {
        setSavedReports(items => editingReport
          ? items.map(item => item.id === result.data.id ? result.data : item)
          : [...items, result.data]);
        clearReportEditor();
        setSavedMessage(editingReport ? 'Saved report updated as a new immutable version.' : 'Saved report created. Only you can see it.');
      } else setSavedMessage('The report could not be saved. Check your workspace access.');
    } catch { setSavedMessage('The saved report request could not be reached.'); }
    finally { setBusy(false); }
  }

  function editSavedReport(report: components['schemas']['SavedReport']) {
    setEditingReport(report);
    setReportName(report.name);
    setOverdueScope(report.definition.scope);
    setReportState(report.definition.filters?.find(filter => filter.field === 'state')?.value ?? '');
    setReportSortDirection(report.definition.sort_direction);
    setReportGroupBy(report.definition.group_by);
    setReportColumns(report.definition.columns);
  }

  function clearReportEditor() {
    setEditingReport(null);
    setReportName('');
    setReportState('');
    setReportSortDirection('asc');
    setReportGroupBy('none');
    setReportColumns(reportColumnChoices.map(item => item.value));
  }

  async function runSavedReport(report: components['schemas']['SavedReport']) {
    if (!organization || !workspace) return;
    setBusy(true); setSavedMessage('');
    try {
      const result = await api.GET('/api/v1/organizations/{organization_id}/workspaces/{workspace_id}/reports/saved/{report_id}/run', {
        params: { path: { organization_id: organization, workspace_id: workspace, report_id: report.id } },
      });
      if (result.data) { setSavedResults(result.data); setSavedMessage(`Showing ${result.data.groups.length} groups and ${result.data.items.length} rows from ${report.name}.`); }
      else setSavedMessage('You no longer have access to this report dataset.');
    } catch { setSavedMessage('You no longer have access to this report dataset.'); }
    finally { setBusy(false); }
  }

  async function downloadSavedReport(
    report: components['schemas']['SavedReport'],
    format: 'csv' | 'xlsx' | 'pdf',
  ) {
    if (!organization || !workspace) return;
    setBusy(true); setSavedMessage('');
    try {
      const result = await api.GET(
        '/api/v1/organizations/{organization_id}/workspaces/{workspace_id}/reports/saved/{report_id}/export',
        {
          params: {
            path: { organization_id: organization, workspace_id: workspace, report_id: report.id },
            query: { format },
          },
          parseAs: 'blob',
        },
      );
      if (result.data) {
        const url = URL.createObjectURL(result.data);
        const link = document.createElement('a');
        link.href = url;
        link.download = `overdue-tasks-${report.id}.${format}`;
        link.click();
        URL.revokeObjectURL(url);
        setSavedMessage(`${format.toUpperCase()} export downloaded.`);
      } else if (result.response.status === 409) {
        const queued = await api.POST('/api/v1/organizations/{organization_id}/workspaces/{workspace_id}/reports/saved/{report_id}/export-jobs', {
          params: { path: { organization_id: organization, workspace_id: workspace, report_id: report.id } },
          body: { format },
        });
        if (queued.data) {
          setExportJobs(current => [queued.data!, ...current.filter(job => job.id !== queued.data?.id)]);
          setSavedMessage(`${format.toUpperCase()} export queued. It will appear below when ready.`);
        } else setSavedMessage('The background export could not be queued.');
      } else setSavedMessage('The export could not be generated.');
    } catch { setSavedMessage('The report export could not be reached.'); }
    finally { setBusy(false); }
  }

  async function refreshExportJobs() {
    if (!organization || !workspace) return;
    const result = await api.GET('/api/v1/organizations/{organization_id}/workspaces/{workspace_id}/reports/export-jobs', {
      params: { path: { organization_id: organization, workspace_id: workspace } },
    });
    if (result.data) setExportJobs(result.data);
  }

  async function downloadExportJob(job: components['schemas']['ReportExportJob']) {
    if (!organization || !workspace) return;
    const result = await api.GET('/api/v1/organizations/{organization_id}/workspaces/{workspace_id}/reports/export-jobs/{job_id}/download', {
      params: { path: { organization_id: organization, workspace_id: workspace, job_id: job.id } },
      parseAs: 'blob',
    });
    if (!result.data) { setSavedMessage('The export is unavailable or your access has changed.'); return; }
    const url = URL.createObjectURL(result.data);
    const link = document.createElement('a');
    link.href = url; link.download = `report-${job.report_id}.${job.format}`; link.click();
    URL.revokeObjectURL(url);
  }

  async function archiveSavedReport(report: components['schemas']['SavedReport']) {
    if (!organization || !workspace) return;
    setBusy(true); setSavedMessage('');
    try {
      const result = await api.POST('/api/v1/organizations/{organization_id}/workspaces/{workspace_id}/reports/saved/{report_id}/archive', {
        params: { path: { organization_id: organization, workspace_id: workspace, report_id: report.id }, query: { expected_version: report.version } },
      });
      if (!result.error) {
        setSavedReports(items => items.filter(item => item.id !== report.id));
        setSavedResults(null); setSavedMessage('Saved report archived.');
      } else setSavedMessage('The report changed or could not be archived. Reload and try again.');
    } catch { setSavedMessage('The saved report request could not be reached.'); }
    finally { setBusy(false); }
  }

  async function createDashboard(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!organization || !workspace || savedReports.length === 0) return;
    const form = new FormData(event.currentTarget);
    const reportId = String(form.get('dashboard_report'));
    const report = savedReports.find(item => item.id === reportId);
    if (!report) { setDashboardMessage('Choose one of your saved reports.'); return; }
    setBusy(true); setDashboardMessage('');
    try {
      const result = await api.POST('/api/v1/organizations/{organization_id}/workspaces/{workspace_id}/reports/dashboards', {
        params: { path: { organization_id: organization, workspace_id: workspace } },
        body: {
          name: String(form.get('dashboard_name')),
          definition: { widgets: [{ report_id: report.id, kind: String(form.get('dashboard_kind')) as components['schemas']['DashboardWidgetDefinition']['kind'], title: String(form.get('dashboard_title')) }] },
        },
      });
      if (result.data) {
        setDashboards(items => [...items, result.data]);
        (event.currentTarget as HTMLFormElement).reset();
        setDashboardMessage('Private dashboard created.');
      } else setDashboardMessage('The dashboard could not be saved. Check your report access.');
    } catch { setDashboardMessage('The dashboard request could not be reached.'); }
    finally { setBusy(false); }
  }

  async function runDashboard(dashboard: components['schemas']['Dashboard']) {
    if (!organization || !workspace) return;
    setBusy(true); setDashboardMessage('');
    try {
      const result = await api.GET('/api/v1/organizations/{organization_id}/workspaces/{workspace_id}/reports/dashboards/{dashboard_id}/run', {
        params: { path: { organization_id: organization, workspace_id: workspace, dashboard_id: dashboard.id } },
      });
      if (result.data) {
        setDashboardResults(items => [...items.filter(item => item.dashboard_id !== dashboard.id), result.data]);
        setDashboardMessage(`Dashboard ${dashboard.name} refreshed.`);
      } else setDashboardMessage('Dashboard data is unavailable with your current access.');
    } catch { setDashboardMessage('Dashboard data is unavailable with your current access.'); }
    finally { setBusy(false); }
  }

  async function archiveDashboard(dashboard: components['schemas']['Dashboard']) {
    if (!organization || !workspace) return;
    setBusy(true); setDashboardMessage('');
    try {
      const result = await api.POST('/api/v1/organizations/{organization_id}/workspaces/{workspace_id}/reports/dashboards/{dashboard_id}/archive', {
        params: { path: { organization_id: organization, workspace_id: workspace, dashboard_id: dashboard.id }, query: { expected_version: dashboard.version } },
      });
      if (!result.error) {
        setDashboards(items => items.filter(item => item.id !== dashboard.id));
        setDashboardResults(items => items.filter(item => item.dashboard_id !== dashboard.id));
        setDashboardMessage('Dashboard archived.');
      } else setDashboardMessage('The dashboard changed or could not be archived. Reload and try again.');
    } catch { setDashboardMessage('The dashboard request could not be reached.'); }
    finally { setBusy(false); }
  }

  async function loadMoreOverdue() {
    if (!organization || !workspace || !overdueCursor) return;
    setOverdueMessage('');
    try {
      const result = await api.GET('/api/v1/organizations/{organization_id}/workspaces/{workspace_id}/reports/overdue-tasks', {
        params: { path: { organization_id: organization, workspace_id: workspace }, query: { cursor: overdueCursor, scope: overdueScope } },
      });
      if (result.data) { setOverdue(items => [...items, ...result.data.items]); setOverdueCursor(result.data.next_cursor); }
      else setOverdueMessage('More overdue tasks could not be loaded.');
    } catch { setOverdueMessage('The overdue task report could not be reached.'); }
  }

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
    event.preventDefault(); setBusy(true); setInvitation(''); setInvitationLink(''); setMessage('');
    const form = new FormData(event.currentTarget);
    try {
      if (form.get('acceptance') === 'verified_email') {
        const fingerprint = JSON.stringify([organization, workspace, form.get('email'), form.get('role'), emailDelivery, form.get('email_reason')]);
        if (invitationRequest.current?.fingerprint !== fingerprint) {
          invitationRequest.current = { fingerprint, id: invitationRequestId() };
        }
        const result = await api.POST('/api/v1/organizations/{organization_id}/invitations/verified-email', {
          params: { path: { organization_id: organization } },
          body: { id: invitationRequest.current.id, email: String(form.get('email')),
            role: String(form.get('role')) as Role, scope_type: 'workspace', scope_id: workspace,
            email_delivery: emailDelivery, email_reason: emailDelivery ? String(form.get('email_reason')) : null },
        });
        if (result.data) {
          invitationRequest.current = undefined;
          setInvitationLink(window.location.origin + invitationPath({ organization: result.data.organization_id, invitation: result.data.id }));
          setMessage(emailDelivery ? 'Sign-in invitation created and email queued. Delivery may be delayed until email is configured.' : 'Sign-in invitation created. Share the link with the invited member.');
        } else setMessage('Invitation could not be created. Check your access and selected role.');
        return;
      }
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
      <button onClick={() => void auth.signinRedirect({ state: { invitation: readInvitationTarget(window.location.search) } }).catch(() => setMessage('Sign-in is unavailable.'))}>Sign in</button>
      <p role="status">{message}</p></section>;
  }
  return <>
    <div className="toolbar"><p>Signed in to your organization</p>
      <button onClick={() => { setMe(undefined); setWorkspaces([]); setInvitation(''); setInvitationLink(''); void auth.removeUser(); }}>Sign out here</button></div>
    <p role="status" aria-live="polite">{message}</p>
    <section><h2>Organization and workspace</h2>
      <label>Organization<select aria-label="Organization" value={organization} onChange={event => { setOrganization(event.target.value); setOverdueScope('personal'); }}>
        <option value="">Choose an organization</option>
        {me?.memberships.map(item => <option key={item.organization_id} value={item.organization_id}>{item.organization_name}</option>)}
      </select></label>
      <label>Workspace<select aria-label="Workspace" value={workspace} onChange={event => { setWorkspace(event.target.value); setInvitation(''); setInvitationLink(''); setOverdueScope('personal'); }}>
        <option value="">Choose a workspace</option>
        {workspaces.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
      </select></label>
      {cursor && <button disabled={busy} onClick={() => void loadMore()}>Load more workspaces</button>}
      {permissions.includes('workspace.create') && <form onSubmit={event => void createWorkspace(event)}>
        <label>Workspace name<input name="name" required maxLength={120} /></label>
        <button disabled={busy}>Create workspace</button>
      </form>}
    </section>
    {organization && workspace && <section aria-labelledby="overdue-heading">
      <h2 id="overdue-heading">{overdueScope === 'personal' ? 'My overdue tasks' : 'Workspace overdue tasks'}</h2>
      <label>Report scope<select aria-label="Report scope" value={overdueScope} onChange={event => setOverdueScope(event.target.value as 'personal' | 'aggregate')}>
        <option value="personal">Assigned to me</option><option value="aggregate">All tasks in this workspace</option>
      </select></label>
      <p>{overdueScope === 'personal' ? 'Only tasks assigned to you in the selected workspace are shown.' : 'All overdue tasks in this workspace are shown. Recipient and claimant identity is not included.'}</p>
      {overdueMessage && <p role="status">{overdueMessage}</p>}
      {overdue.length === 0 && !overdueMessage ? <p>No overdue tasks.</p> : <table>
        <caption className="sr-only">Your overdue tasks</caption>
        <thead><tr><th scope="col">Task</th><th scope="col">Type</th><th scope="col">Due</th><th scope="col">Status</th></tr></thead>
        <tbody>{overdue.map(task => <tr key={task.id}><th scope="row">{task.name}</th><td>{task.kind}</td><td>{task.due_at ? new Date(task.due_at).toLocaleString() : ''}</td><td>{task.state}</td></tr>)}</tbody>
      </table>}
      {overdueCursor && <button onClick={() => void loadMoreOverdue()}>Load more overdue tasks</button>}
    </section>}
    {organization && workspace && <section aria-labelledby="saved-reports-heading">
      <h2 id="saved-reports-heading">My saved reports</h2>
      <p>Saved report definitions are private to your account. Aggregate reports require schedule management access each time they run.</p>
      <form onSubmit={event => void createSavedReport(event)}>
        <label>Report name<input name="report_name" required maxLength={120} value={reportName} onChange={event => setReportName(event.target.value)} /></label>
        <label>Task state filter<select aria-label="Task state filter" name="report_state" value={reportState} onChange={event => setReportState(event.target.value)}><option value="">All overdue states</option><option value="open">Open</option><option value="in_progress">In progress</option><option value="returned">Returned</option></select></label>
        <label>Sort by task ID<select aria-label="Sort direction" name="report_sort_direction" value={reportSortDirection} disabled={reportGroupBy !== 'none'} onChange={event => setReportSortDirection(event.target.value as typeof reportSortDirection)}><option value="asc">Oldest first</option><option value="desc">Newest first</option></select></label>
        <label>Group results<select aria-label="Group results" name="report_group_by" value={reportGroupBy} onChange={event => {
          const value = event.target.value as typeof reportGroupBy;
          setReportGroupBy(value);
          if (value === 'state') { setReportColumns(['state']); setReportSortDirection('asc'); }
          if (value === 'due_week') { setReportColumns(['due_at']); setReportSortDirection('asc'); }
          if (value === 'none') setReportColumns(['id', 'project_id', 'kind', 'name', 'state', 'due_at']);
        }}><option value="none">No grouping</option><option value="state">Count by task state</option><option value="due_week">Overdue count by due-date week</option></select></label>
        <fieldset><legend>Report columns</legend>
          {reportColumnChoices.map(column => <label key={column.value}><input type="checkbox" name="report_columns" value={column.value} checked={reportColumns.includes(column.value)} disabled={reportGroupBy !== 'none' && column.value !== (reportGroupBy === 'state' ? 'state' : 'due_at')} onChange={event => setReportColumns(current => event.target.checked ? [...current, column.value] : current.filter(item => item !== column.value))} />{column.label}</label>)}
        </fieldset>
        <button disabled={busy}>{editingReport ? 'Update saved report' : 'Save current overdue report'}</button>
        {editingReport && <button type="button" disabled={busy} onClick={clearReportEditor}>Cancel edit</button>}
      </form>
      {savedMessage && <p role="status">{savedMessage}</p>}
      {savedReports.length === 0 && <p>No saved reports.</p>}
      <ul>{savedReports.map(report => <li key={report.id}>
        <span>{report.name} · {report.definition.scope} · version {report.version}</span>{' '}
        <button disabled={busy} onClick={() => editSavedReport(report)}>Edit</button>{' '}
        <button disabled={busy} onClick={() => void runSavedReport(report)}>Run</button>{' '}
        <button disabled={busy} onClick={() => void downloadSavedReport(report, 'csv')}>Export CSV</button>{' '}
        <button disabled={busy} onClick={() => void downloadSavedReport(report, 'xlsx')}>Export XLSX</button>{' '}
        <button disabled={busy} onClick={() => void downloadSavedReport(report, 'pdf')}>Export PDF</button>{' '}
        <button disabled={busy} onClick={() => void archiveSavedReport(report)}>Archive</button>
      </li>)}</ul>
      <h3>My export jobs</h3>
      <button type="button" onClick={() => void refreshExportJobs()}>Refresh export status</button>
      {exportJobs.length === 0 ? <p>No recent export jobs.</p> : <ul>{exportJobs.map(job => <li key={job.id}>
        <span>{job.format.toUpperCase()} · report version {job.report_version} · {job.state}</span>{' '}
        {job.state === 'completed' && <button type="button" onClick={() => void downloadExportJob(job)}>Download</button>}
        {job.error_code && <span> ({job.error_code})</span>}
      </li>)}</ul>}
      {savedResults && savedResults.groups.length > 0 && <table>
        <caption>Saved report counts by task state</caption>
        <thead><tr><th scope="col">Task state</th><th scope="col">Task count</th></tr></thead>
        <tbody>{savedResults.groups.map(group => <tr key={group.state}><th scope="row">{group.state}</th><td>{group.count}</td></tr>)}</tbody>
      </table>}
      {savedResults && savedResults.items.length > 0 && <table>
        <caption>Saved report results</caption>
        <thead><tr><th scope="col">Task</th><th scope="col">Type</th><th scope="col">Due</th><th scope="col">Status</th></tr></thead>
        <tbody>{savedResults.items.map((row, index) => <tr key={row.id ?? index}><th scope="row">{row.name}</th><td>{row.kind}</td><td>{row.due_at ? new Date(row.due_at).toLocaleString() : ''}</td><td>{row.state}</td></tr>)}</tbody>
      </table>}
    </section>}
    {organization && workspace && <section aria-labelledby="dashboards-heading">
      <h2 id="dashboards-heading">My dashboards</h2>
      <p>Dashboards are private to you. Each widget runs its saved report with current access checks.</p>
      <form onSubmit={event => void createDashboard(event)}>
        <label>Dashboard name<input name="dashboard_name" required maxLength={120} /></label>
        <label>Saved report<select name="dashboard_report" required disabled={savedReports.length === 0}>
          {savedReports.length === 0 ? <option value="">Save a report first</option> : savedReports.map(report => <option key={report.id} value={report.id}>{report.name}</option>)}
        </select></label>
        <label>Widget title<input name="dashboard_title" required maxLength={80} defaultValue="Overdue work" /></label>
        <label>Widget shape<select name="dashboard_kind"><option value="table">Table</option><option value="overdue_list">Overdue list</option><option value="status_distribution">Status distribution (requires a state-grouped report)</option><option value="bar">Bar chart (task count by state)</option><option value="trend">Trend (overdue count by due-date week)</option><option value="line">Line chart (overdue count by due-date week)</option><option value="metric">Overdue task count (requires a state-grouped report)</option></select></label>
        <button disabled={busy || savedReports.length === 0}>Create dashboard</button>
      </form>
      {dashboardMessage && <p role="status">{dashboardMessage}</p>}
      {dashboards.length === 0 && <p>No dashboards.</p>}
      <ul>{dashboards.map(dashboard => <li key={dashboard.id}>
        <span>{dashboard.name} · version {dashboard.version}</span>{' '}
        <button disabled={busy} onClick={() => void runDashboard(dashboard)}>Run dashboard</button>{' '}
        <button disabled={busy} onClick={() => void archiveDashboard(dashboard)}>Archive dashboard</button>
      </li>)}</ul>
      {dashboardResults.map(result => <section key={result.dashboard_id} aria-label="Dashboard results">
        <h3>Dashboard results</h3>
        {result.widgets.map((widget, index) => widget.kind === 'metric'
          ? <div key={`${result.dashboard_id}-${index}`} aria-label={widget.title}>
            <h4>{widget.title}</h4><output>{widget.metric_value ?? 0}</output><span> overdue tasks</span>
          </div>
          : widget.kind === 'bar'
            ? <figure key={`${result.dashboard_id}-${index}`} aria-label={widget.title}>
              <figcaption>{widget.title}</figcaption>
              <ul>{widget.report.groups.map(group => <li key={group.state}>
                <span>{group.state}</span>{' '}<meter min={0} max={Math.max(...widget.report.groups.map(item => item.count))} value={group.count}>{group.count}</meter>{' '}{group.count}
              </li>)}</ul>
            </figure>
            : widget.kind === 'trend' || widget.kind === 'line'
              ? (() => {
                const groups = widget.report.due_week_groups;
                const weeks = groups.filter(group => group.week_start !== null);
                const maxCount = Math.max(1, ...weeks.map(group => group.count));
                const points = weeks.map((group, pointIndex) => {
                  const x = 20 + pointIndex * (440 / Math.max(1, weeks.length - 1));
                  const y = 160 - group.count / maxCount * 135;
                  return `${x},${y}`;
                }).join(' ');
                const older = groups.find(group => group.week_start === null);
                return <figure key={`${result.dashboard_id}-${index}`} aria-label={widget.title}>
                  <figcaption>{widget.title} · current overdue count by due-date week</figcaption>
                  <svg viewBox="0 0 480 180" role="img" aria-label={`Counts across ${weeks.length} UTC due-date weeks`}>
                    <polyline points={points} fill="none" stroke="currentColor" strokeWidth="3" />
                  </svg>
                  <p>{older?.label}: {older?.count ?? 0} tasks</p>
                  <table><caption>Weekly counts</caption><thead><tr><th scope="col">UTC week starting</th><th scope="col">Current overdue tasks</th></tr></thead>
                    <tbody>{weeks.map(group => <tr key={group.label}><th scope="row">{group.label}</th><td>{group.count}</td></tr>)}</tbody>
                  </table>
                </figure>;
              })()
              : <table key={`${result.dashboard_id}-${index}`}>
          <caption>{widget.title}</caption>
          {widget.kind === 'status_distribution'
            ? <thead><tr><th scope="col">Task state</th><th scope="col">Task count</th></tr></thead>
            : <thead><tr><th scope="col">Task</th><th scope="col">Type</th><th scope="col">Due</th><th scope="col">Status</th></tr></thead>}
          <tbody>{widget.report.groups.length > 0
            ? widget.report.groups.map(group => <tr key={group.state}><th scope="row">{group.state}</th><td>{group.count}</td></tr>)
            : widget.report.items.map((row, rowIndex) => <tr key={row.id ?? rowIndex}><th scope="row">{row.name}</th><td>{row.kind}</td><td>{row.due_at ? new Date(row.due_at).toLocaleString() : ''}</td><td>{row.state}</td></tr>)}</tbody>
        </table>)}
      </section>)}
    </section>}
    {permissions.includes('iam.grants.manage') && workspace && <section><h2>Invite a workspace member</h2>
      <p>Review the selected organization and workspace before creating access.</p>
      <form onSubmit={event => void createInvitation(event)}>
        <label>Email<input type="email" name="email" required /></label>
        <label>Role<select name="role" aria-label="Role"><option>Viewer</option><option>Contributor</option><option>Reviewer</option><option>Approver</option><option>WorkspaceAdmin</option><option>WorkspaceOwner</option></select></label>
        <label>Invitation method<select name="acceptance" aria-label="Invitation method" value={acceptance} onChange={event => { setAcceptance(event.target.value); setEmailDelivery(false); }}><option value="token">Invitation code</option><option value="verified_email">Verified email sign-in link</option></select></label>
        {acceptance === 'verified_email' && permissions.includes('organization.manage') && <>
          <label><input type="checkbox" checked={emailDelivery} onChange={event => setEmailDelivery(event.target.checked)} />Email the sign-in invitation</label>
          {emailDelivery && <label>Email request reason<input name="email_reason" required maxLength={500} /></label>}
        </>}
        <button disabled={busy}>Create invitation</button>
      </form>
      {invitation && <div><p>Share this code and organization ID with the intended member. The code expires in seven days.</p>
        <label>Invitation code<textarea readOnly value={invitation} /></label></div>}
      {invitationLink && <div><p>This link expires in seven days. Share it only with the intended member.</p>
        <label>Sign-in invitation link<textarea aria-label="Sign-in invitation link" readOnly value={invitationLink} /></label></div>}
    </section>}
    {organization && permissions.includes('organization.manage') && <EmailRecovery key={'email' + organization} api={api} organization={organization}/>}
    {organization && (permissions.includes('integration.manage') || permissions.includes('organization.manage')) && <WebhookRecovery key={'webhook-recovery' + organization} api={api} organization={organization}/>}
    {organization && (permissions.includes('integration.manage') || permissions.includes('organization.manage') || (workspace && permissions.includes('workspace.manage'))) && <WebhookEndpoints key={'webhook' + organization + workspace} api={api} organization={organization} workspace={workspace || undefined}/>}
    {organization && workspace && <Notifications key={'notifications' + organization + workspace} api={api} organization={organization} workspace={workspace} />}
    {organization && workspace && <ProjectAdministration key={organization + workspace} api={api} organization={organization} workspace={workspace} userId={me?.memberships.find(item=>item.organization_id===organization)?.user_id??''} />}
    <section><h2>Accept an invitation</h2><form onSubmit={event => void acceptInvitation(event)}>
      <label>Organization ID<input name="organization" required /></label>
      <label>Invitation code<input name="token" type="password" autoComplete="off" required /></label>
      <button disabled={busy}>Accept invitation</button>
    </form></section>
    <InvitationAcceptance api={api} target={invitationTargetFromState(auth.user?.state) ?? readInvitationTarget(window.location.search)} onAccepted={async selected => {
      const refreshed = await api.GET('/api/v1/me');
      if (refreshed.data) { setMe(refreshed.data); setOrganization(selected); }
    }} />
  </>;
}
