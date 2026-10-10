import { useEffect, useRef, useState, type FormEvent } from 'react';
import type { components } from './api-schema';
import type { apiClient } from './client';
import { metadataStarter, parseAutomationDefinition } from './automation-definition';
type Client = ReturnType<typeof apiClient>;
type Rule = components['schemas']['Rule'];
type Version = components['schemas']['RuleVersion'];
type Run = components['schemas']['Run'];
type History = components['schemas']['RunHistory'];
type Review = components['schemas']['RunReplayReview'];
const base = '/api/v1/organizations/{organization_id}/workspaces/{workspace_id}/automation-rules' as const;
const versionPath = `${base}/{rule_id}/versions/{number}` as const;
const historyPath = `${base}/{rule_id}/runs/{run_id}` as const;
function failure(error: unknown): string { return error && typeof error === 'object' && 'code' in error ? String(error.code) : 'Request could not be completed.'; }

export function Automation({ api, organization, workspace, project }: { api: Client; organization: string; workspace: string; project: string }) {
  const path = { organization_id: organization, workspace_id: workspace };
  const [rules, setRules] = useState<Rule[]>([]);
  const [ruleCursor, setRuleCursor] = useState<string | null>(null);
  const [selected, setSelected] = useState('');
  const [versions, setVersions] = useState<Version[]>([]);
  const [versionCursor, setVersionCursor] = useState<string | null>(null);
  const [version, setVersion] = useState<Version>();
  const [definition, setDefinition] = useState(JSON.stringify(metadataStarter, null, 2));
  const [activation, setActivation] = useState<Version>();
  const [runs, setRuns] = useState<Run[]>([]);
  const [runCursor, setRunCursor] = useState<string | null>(null);
  const [history, setHistory] = useState<History>();
  const [replay, setReplay] = useState<Review>();
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const generation = useRef(0);
  const rule = rules.find(row => row.id === selected);
  async function run(work: () => Promise<void>) { setBusy(true); setMessage(''); try { await work(); } catch (error) { setMessage(error instanceof Error ? error.message : failure(error)); } finally { setBusy(false); } }
  async function loadRules(after?: string) {
    const result = await api.GET(base, { params: { path, query: { project_id: project || null, cursor: after ?? null } } });
    if (!result.data) throw new Error(failure(result.error));
    setRules(current => after ? [...current, ...result.data.items] : result.data.items); setRuleCursor(result.data.next_cursor ?? null);
  }
  async function loadVersions(after?: string) {
    const ticket = generation.current;
    const result = await api.GET(`${base}/{rule_id}/versions`, { params: { path: { ...path, rule_id: selected }, query: { cursor: after ?? null } } });
    if (ticket !== generation.current) return;
    if (!result.data) throw new Error(failure(result.error));
    setVersions(current => after ? [...current, ...result.data.items] : result.data.items); setVersionCursor(result.data.next_cursor ?? null);
  }
  async function loadRuns(after?: string) {
    if (!version) return; const ticket = generation.current;
    const result = await api.GET(`${versionPath}/runs`, { params: { path: { ...path, rule_id: selected, number: version.number }, query: { cursor: after ?? null } } });
    if (ticket !== generation.current) return;
    if (!result.data) throw new Error(failure(result.error));
    setRuns(current => after ? [...current, ...result.data.items] : result.data.items); setRunCursor(result.data.next_cursor ?? null);
  }
  async function loadHistory(id: string) {
    const ticket = generation.current; setHistory(undefined); setReplay(undefined); setReason('');
    const result = await api.GET(historyPath, { params: { path: { ...path, rule_id: selected, run_id: id } } });
    if (ticket !== generation.current) return;
    if (!result.data) throw new Error(failure(result.error)); setHistory(result.data);
  }
  useEffect(() => {
    let alive = true;
    void api.GET(base, { params: { path, query: { project_id: project || null } } }).then(result => {
      if (!alive) return;
      if (result.data) { setRules(result.data.items); setRuleCursor(result.data.next_cursor ?? null); } else setMessage(failure(result.error));
    }).catch(() => { if (alive) setMessage('Automation administration could not be loaded.'); });
    return () => { alive = false; generation.current++; };
  }, [api, organization, workspace, project]);
  useEffect(() => {
    const ticket = ++generation.current;
    setVersions([]); setVersion(undefined); setVersionCursor(null); setActivation(undefined); setRuns([]); setRunCursor(null); setHistory(undefined); setReplay(undefined); setReason(''); setDefinition(JSON.stringify(metadataStarter, null, 2));
    if (selected) void api.GET(`${base}/{rule_id}/versions`, { params: { path: { ...path, rule_id: selected } } }).then(result => {
      if (ticket !== generation.current) return;
      if (result.data) { setVersions(result.data.items); setVersionCursor(result.data.next_cursor ?? null); } else setMessage(failure(result.error));
    }).catch(() => { if (ticket === generation.current) setMessage('Rule versions could not be loaded.'); });
    return () => { generation.current++; };
  }, [api, organization, workspace, selected]);
  function chooseVersion(row: Version) { generation.current++; setVersion(row); setDefinition(JSON.stringify(row.definition, null, 2)); setActivation(undefined); setRuns([]); setRunCursor(null); setHistory(undefined); setReplay(undefined); setReason(''); }
  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = event.currentTarget; const name = String(new FormData(form).get('name'));
    await run(async () => {
      const result = await api.POST(base, { params: { path }, body: { name, project_id: project || null, definition: parseAutomationDefinition(definition) } });
      if (!result.data) throw new Error(failure(result.error)); await loadRules(); setSelected(result.data.id); form.reset(); setMessage('Automation draft created.');
    });
  }
  async function save() {
    if (!version) return;
    await run(async () => {
      const result = await api.PUT(versionPath, { params: { path: { ...path, rule_id: selected, number: version.number } }, body: { expected_revision: version.revision, definition: parseAutomationDefinition(definition) } });
      if (!result.data) throw new Error(failure(result.error)); chooseVersion(result.data); await loadVersions(); setMessage('Automation draft saved.');
    });
  }
  async function activate(apply: boolean) {
    if (!version || (apply && !activation)) return;
    await run(async () => {
      const result = await api.POST(`${versionPath}/activate`, { params: { path: { ...path, rule_id: selected, number: version.number } }, body: { expected_revision: version.revision, dry_run: !apply, expected_sha256: apply ? activation?.content_sha256 ?? null : null } });
      if (!result.data) throw new Error(failure(result.error));
      if (apply) { chooseVersion(result.data); await loadRules(); await loadVersions(); setMessage('Automation version activated.'); }
      else { setActivation(result.data); setMessage('Activation preview ready. Review the saved definition before applying.'); }
    });
  }
  async function clone(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!version) return; const number = Number(new FormData(event.currentTarget).get('number'));
    await run(async () => {
      const result = await api.POST(`${base}/{rule_id}/versions`, { params: { path: { ...path, rule_id: selected } }, body: { source_number: version.number, number } });
      if (!result.data) throw new Error(failure(result.error)); chooseVersion(result.data); await loadVersions(); setMessage('New automation draft cloned.');
    });
  }
  async function retire() {
    if (!rule) return;
    await run(async () => {
      const result = await api.POST(`${base}/{rule_id}/retire`, { params: { path: { ...path, rule_id: selected } }, body: { expected_revision: rule.revision, reason } });
      if (!result.data) throw new Error(failure(result.error)); setVersion(undefined); setActivation(undefined); await loadRules(); await loadVersions(); setMessage('Rule retired. Captured runs retain their pinned versions.');
    });
  }
  async function replayRun(apply: boolean) {
    if (!history || (apply && !replay)) return;
    await run(async () => {
      const result = await api.POST(`${historyPath}/replay`, { params: { path: { ...path, rule_id: selected, run_id: history.run.id } }, body: { dry_run: !apply, review_sha256: apply ? replay?.review_sha256 ?? null : null, reason: apply ? reason : null } });
      if (!result.data) throw new Error(failure(result.error));
      if (apply) { await loadHistory(history.run.id); await loadRuns(); setMessage('Run queued for replay. Previous attempts are preserved.'); }
      else { setReplay(result.data); setMessage('Replay preview ready. Review the run and provide a reason.'); }
    });
  }
  return <section aria-label="Automation administration">
    <h2>Automation</h2><p>Rules use the selected workspace or project. Activation requires an organization administrator.</p><p role="status">{message}</p>
    <button disabled={busy} onClick={() => void run(() => loadRules())}>Refresh automation rules</button>
    {ruleCursor && <button disabled={busy} onClick={() => void run(() => loadRules(ruleCursor))}>More automation rules</button>}
    <label>Automation rule<select aria-label="Automation rule" value={selected} disabled={busy} onChange={event => setSelected(event.target.value)}><option value="">New rule</option>{rules.map(row => <option key={row.id} value={row.id}>{row.name} — {row.active_number ? `active v${row.active_number}` : 'inactive'}</option>)}</select></label>
    {!selected && <form onSubmit={event => void create(event)}><label>Automation name<input name="name" required maxLength={120}/></label><button disabled={busy}>Create automation draft</button></form>}
    {selected && <><button disabled={busy} onClick={() => void run(() => loadVersions())}>Refresh automation versions</button>{versionCursor && <button disabled={busy} onClick={() => void run(() => loadVersions(versionCursor))}>More automation versions</button>}
      <label>Automation version<select aria-label="Automation version" value={version?.id ?? ''} disabled={busy} onChange={event => { const row = versions.find(item => item.id === event.target.value); if (row) chooseVersion(row); }}><option value="">Choose a version</option>{versions.map(row => <option key={row.id} value={row.id}>v{row.number} — {row.state}</option>)}</select></label></>}
    <label>Automation definition<textarea aria-label="Automation definition" rows={14} value={definition} disabled={busy || (!!selected && version?.state !== 'draft')} onChange={event => { setDefinition(event.target.value); setActivation(undefined); }}/></label>
    {version && <><p>Version {version.number}: {version.state}, revision {version.revision}</p>
      {version.state === 'draft' && <><button disabled={busy} onClick={() => void save()}>Save automation draft</button><button disabled={busy || definition !== JSON.stringify(version.definition, null, 2)} onClick={() => void activate(false)}>Preview automation activation</button></>}
      {activation && <><pre>{JSON.stringify(activation.definition, null, 2)}</pre><p>Reviewed content: {activation.content_sha256}</p><button disabled={busy} onClick={() => void activate(true)}>Apply automation activation</button></>}
      <form onSubmit={event => void clone(event)}><label>New automation version number<input name="number" type="number" min={1} required/></label><button disabled={busy}>Clone automation version</button></form>
      <button disabled={busy} onClick={() => void run(() => loadRuns())}>Refresh automation runs</button>{runCursor && <button disabled={busy} onClick={() => void run(() => loadRuns(runCursor))}>More automation runs</button>}
      <ul>{runs.map(row => <li key={row.id}><button disabled={busy} onClick={() => void run(() => loadHistory(row.id))}>{row.state} — {row.id} — {row.attempts} attempts</button></li>)}</ul>
    </>}
    {history && <><h3>Run evidence</h3><p>{history.run.state} — correlation {history.run.correlation_id}</p><p>Created {history.run.created_at}; next attempt {history.run.next_at}; completed {history.run.completed_at ?? 'pending'}; error {history.run.error_code ?? 'none'}.</p>
      <ul>{history.attempts.map(row => <li key={row.id}>Attempt {row.number}: {row.outcome} — {row.error_code ?? 'none'} — {row.started_at} to {row.finished_at}</li>)}</ul>
      <ul>{history.receipts.map(row => <li key={row.id}>Action {row.position + 1}: {row.kind} — target {row.target_id ?? 'none'} — {row.created_at}</li>)}</ul>
      <button disabled={busy} onClick={() => void run(() => loadHistory(history.run.id))}>Refresh automation run evidence</button>
      {['retry', 'dead_letter'].includes(history.run.state) && history.run.attempts < 20 && <button disabled={busy} onClick={() => void replayRun(false)}>Preview automation replay</button>}
      {replay && <><p>Reviewed run: {replay.run.state}, {replay.run.attempts} attempts. Review {replay.review_sha256}.</p><button disabled={busy || !reason.trim()} onClick={() => void replayRun(true)}>Apply automation replay</button></>}
    </>}
    {selected && <label>Automation change reason<input value={reason} maxLength={500} disabled={busy} onChange={event => setReason(event.target.value)}/></label>}
    {rule?.active_number && <button disabled={busy || !reason.trim()} onClick={() => void retire()}>Retire automation rule</button>}
  </section>;
}
