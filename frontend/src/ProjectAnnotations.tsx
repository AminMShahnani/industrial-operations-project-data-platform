import { useEffect, useRef, useState } from 'react';
import type { components } from './api-schema';
import type { apiClient } from './client';

type Annotation = components['schemas']['ProjectAnnotation'];
const endpoint = '/api/v1/organizations/{organization_id}/workspaces/{workspace_id}/projects/{project_id}/annotations' as const;
function failure(error: unknown): string {
  return error && typeof error === 'object' && 'code' in error ? String(error.code) : 'Project labels could not be loaded.';
}

export function ProjectAnnotations({ api, organization, workspace, project }: {
  api: ReturnType<typeof apiClient>; organization: string; workspace: string; project: string;
}) {
  const [rows, setRows] = useState<Annotation[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [kind, setKind] = useState<'all' | 'tag' | 'flag'>('all');
  const [refresh, setRefresh] = useState(0);
  const [busy, setBusy] = useState(true);
  const [message, setMessage] = useState('');
  const request = useRef(0);
  const path = { organization_id: organization, workspace_id: workspace, project_id: project };
  const query = kind === 'all' ? {} : { kind };

  useEffect(() => {
    const generation = ++request.current;
    setRows([]); setCursor(null); setMessage(''); setBusy(true);
    void api.GET(endpoint, { params: { path, query } }).then(result => {
      if (request.current !== generation) return;
      if (result.data) { setRows(result.data.items); setCursor(result.data.next_cursor); }
      else setMessage(failure(result.error));
    }).catch(() => {
      if (request.current === generation) setMessage('Project labels could not be loaded.');
    }).finally(() => { if (request.current === generation) setBusy(false); });
    return () => { request.current += 1; };
  }, [api, organization, workspace, project, kind, refresh]);

  async function more() {
    if (busy || !cursor) return;
    const generation = request.current;
    setBusy(true); setMessage('');
    try {
      const result = await api.GET(endpoint, { params: { path, query: { ...query, cursor } } });
      if (request.current !== generation) return;
      if (result.data) { setRows(current => [...current, ...result.data!.items]); setCursor(result.data.next_cursor); }
      else setMessage(failure(result.error));
    } catch {
      if (request.current === generation) setMessage('Project labels could not be loaded.');
    } finally { if (request.current === generation) setBusy(false); }
  }

  return <section aria-label="Project tags and flags">
    <h3>Project tags and flags</h3>
    <label>Project label kind<select aria-label="Project label kind" value={kind} onChange={event => setKind(event.target.value as typeof kind)}>
      <option value="all">All labels</option><option value="tag">Tags</option><option value="flag">Flags</option>
    </select></label>
    <button disabled={busy} onClick={() => setRefresh(value => value + 1)}>Refresh project labels</button>
    <p role="status">{message || (busy ? 'Loading project labels…' : '')}</p>
    <ul>{rows.map(row => <li key={row.id}><strong>{row.kind}: {row.value}</strong>
      <small> — Added {new Date(row.created_at).toLocaleString()} by {row.created_by_id}</small>
    </li>)}</ul>
    {!busy && !rows.length && !message && <p>No labels in this view.</p>}
    {cursor && <button disabled={busy} onClick={() => void more()}>Load more project labels</button>}
  </section>;
}
