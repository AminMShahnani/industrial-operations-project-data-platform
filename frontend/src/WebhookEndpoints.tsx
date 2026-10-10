import { useEffect, useRef, useState, type FormEvent } from 'react';
import type { components } from './api-schema';
import type { apiClient } from './client';

type Endpoint = components['schemas']['EndpointView'];
type Scope = 'organization' | 'workspace';
const base = '/api/v1/organizations/{organization_id}/webhook-endpoints' as const;
function failure(error: unknown): string {
  return error && typeof error === 'object' && 'code' in error
    ? String(error.code)
    : 'Webhook endpoints could not be loaded.';
}

export function WebhookEndpoints({
  api,
  organization,
  workspace,
}: {
  api: ReturnType<typeof apiClient>;
  organization: string;
  workspace?: string | undefined;
}) {
  const [scope, setScope] = useState<Scope>('organization');
  const [endpoints, setEndpoints] = useState<Endpoint[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [selected, setSelected] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const generation = useRef(0);
  const currentWorkspace = scope === 'workspace' ? workspace : undefined;
  const query = { workspace_id: currentWorkspace ?? null, project_id: null };
  const selectedEndpoint = endpoints.find(row => row.endpoint_id === selected);

  async function load(after?: string) {
    const ticket = generation.current;
    const result = await api.GET(base, {
      params: { path: { organization_id: organization }, query: { ...query, cursor: after ?? null } },
    });
    if (ticket !== generation.current) return;
    if (!result.data) throw new Error(failure(result.error));
    setEndpoints(rows => after ? [...rows, ...result.data.items] : result.data.items);
    setCursor(result.data.next_cursor ?? null);
  }

  async function run(work: () => Promise<void>) {
    setBusy(true);
    setMessage('');
    try { await work(); }
    catch (error) { setMessage(error instanceof Error ? error.message : failure(error)); }
    finally { setBusy(false); }
  }

  useEffect(() => {
    const ticket = ++generation.current;
    setEndpoints([]);
    setCursor(null);
    setSelected('');
    setBusy(true);
    setMessage('');
    void api.GET(base, {
      params: {
        path: { organization_id: organization },
        query: { workspace_id: currentWorkspace ?? null, project_id: null },
      },
    }).then(result => {
      if (ticket !== generation.current) return;
      if (result.data) {
        setEndpoints(result.data.items);
        setCursor(result.data.next_cursor ?? null);
      } else setMessage(failure(result.error));
    }).catch(() => {
      if (ticket === generation.current) setMessage('Webhook endpoints could not be loaded.');
    }).finally(() => {
      if (ticket === generation.current) setBusy(false);
    });
    return () => { generation.current++; };
  }, [api, organization, currentWorkspace]);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    await run(async () => {
      const result = await api.POST(base, {
        params: { path: { organization_id: organization }, query },
        body: {
          name: String(data.get('name')).trim(),
          url: String(data.get('url')).trim(),
          secret_reference: String(data.get('secret_reference')).trim(),
          signing_key_version: Number(data.get('signing_key_version')),
        },
      });
      if (!result.data) throw new Error(failure(result.error));
      form.reset();
      await load();
      setMessage('Webhook endpoint created. Its secret reference is never returned by the API.');
    });
  }

  async function revise(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedEndpoint) return;
    const form = event.currentTarget;
    const data = new FormData(form);
    await run(async () => {
      const result = await api.POST(`${base}/{endpoint_id}/versions`, {
        params: {
          path: { organization_id: organization, endpoint_id: selectedEndpoint.endpoint_id },
        },
        body: {
          expected_version: selectedEndpoint.version,
          name: String(data.get('name')).trim(),
          url: String(data.get('url')).trim(),
          secret_reference: String(data.get('secret_reference')).trim(),
          signing_key_version: Number(data.get('signing_key_version')),
        },
      });
      if (!result.data) throw new Error(failure(result.error));
      form.reset();
      setSelected(result.data.endpoint_id);
      await load();
      setMessage(`Endpoint version ${result.data.version} created. Previous versions remain immutable.`);
    });
  }

  async function revoke(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedEndpoint) return;
    const data = new FormData(event.currentTarget);
    await run(async () => {
      const result = await api.POST(`${base}/{endpoint_id}/revoke`, {
        params: {
          path: { organization_id: organization, endpoint_id: selectedEndpoint.endpoint_id },
        },
        body: {
          expected_version: selectedEndpoint.version,
          reason: String(data.get('reason')).trim(),
        },
      });
      if (!result.data) throw new Error(failure(result.error));
      await load();
      setMessage('Endpoint revoked. The revocation is retained as an immutable version.');
    });
  }

  return <section aria-label="Webhook endpoint administration">
    <h2>Webhook endpoints</h2>
    <p>Manage versioned HTTPS destinations for this scope. Signing keys must be pre-provisioned in the deployment secret manager. Key references are write-only here; this screen never displays them.</p>
    <label>Endpoint scope<select aria-label="Webhook endpoint scope" value={scope} disabled={busy} onChange={event => setScope(event.target.value as Scope)}>
      <option value="organization">Organization</option>
      {workspace && <option value="workspace">Selected workspace</option>}
    </select></label>
    <p role="status" aria-live="polite">{message}</p>
    <button disabled={busy} onClick={() => void run(() => load())}>Refresh webhook endpoints</button>
    {cursor && <button disabled={busy} onClick={() => void run(() => load(cursor))}>More webhook endpoints</button>}
    {!busy && !endpoints.length && <p>No endpoints in this scope.</p>}
    <ul>{endpoints.map(row => <li key={row.endpoint_id}>
      <button disabled={busy} onClick={() => setSelected(row.endpoint_id)} aria-pressed={selected === row.endpoint_id}>
        {row.name} — {row.state} — v{row.version} — key v{row.signing_key_version}
      </button>
    </li>)}</ul>
    {selectedEndpoint && <>
      <h3>Endpoint details</h3>
      <p>{selectedEndpoint.name}: {selectedEndpoint.url}; version {selectedEndpoint.version}, key version {selectedEndpoint.signing_key_version}, {selectedEndpoint.state}.</p>
      <p>Secret reference: {selectedEndpoint.secret_reference_present ? 'configured (value hidden)' : 'not configured'}.</p>
      {selectedEndpoint.state === 'active' && <>
        <form onSubmit={event => void revise(event)}>
          <h4>Create a new endpoint version</h4>
          <label>Endpoint name<input name="name" required maxLength={120} defaultValue={selectedEndpoint.name} /></label>
          <label>HTTPS destination<input name="url" type="url" required maxLength={2048} defaultValue={selectedEndpoint.url} /></label>
          <label>External secret reference<input name="secret_reference" required maxLength={512} autoComplete="off" /></label>
          <label>Signing key version<input name="signing_key_version" type="number" min={1} required defaultValue={selectedEndpoint.signing_key_version} /></label>
          <button disabled={busy}>Save new endpoint version</button>
        </form>
        <form onSubmit={event => void revoke(event)}>
          <h4>Revoke endpoint</h4>
          <label>Revocation reason<input name="reason" required maxLength={500} /></label>
          <button disabled={busy}>Revoke endpoint</button>
        </form>
      </>}
    </>}
    <form onSubmit={event => void create(event)}>
      <h3>Register an endpoint</h3>
      <label>Endpoint name<input name="name" required maxLength={120} /></label>
      <label>HTTPS destination<input name="url" type="url" required maxLength={2048} placeholder="https://example.invalid/hooks/operations" /></label>
      <label>External secret reference<input name="secret_reference" required maxLength={512} autoComplete="off" /></label>
      <label>Signing key version<input name="signing_key_version" type="number" min={1} required defaultValue={1} /></label>
      <button disabled={busy}>Register webhook endpoint</button>
    </form>
  </section>;
}
