import { useEffect, useState, type FormEvent } from 'react';
import type { components } from './api-schema';
import type { apiClient } from './client';
import { recordValues } from './master-data-values';

type DataType = components['schemas']['DataType'];
type Record = components['schemas']['DataRecord'];
type Preview = components['schemas']['ImportPreview'];
type DataField = components['schemas']['DataField'];
type Client = ReturnType<typeof apiClient>;
const typesPath = '/api/v1/organizations/{organization_id}/master-data/types' as const;
const recordsPath = '/api/v1/organizations/{organization_id}/master-data/types/{type_id}/records' as const;

export function MasterDataAdmin({ api, organization, workspace, project, canManage }: {
  api: Client; organization: string; workspace: string; project: string; canManage: boolean;
}) {
  const [types, setTypes] = useState<DataType[]>([]);
  const [selected, setSelected] = useState('');
  const [records, setRecords] = useState<Record[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [typeCursor, setTypeCursor] = useState<string | null>(null);
  const [fields, setFields] = useState<DataField[]>([]);
  const [preview, setPreview] = useState<Preview>();
  const [upload, setUpload] = useState<{ data: string; format: 'csv' | 'xlsx' }>();
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [pendingStatus, setPendingStatus] = useState<{ record: Record; status: Record['status'] }>();
  const definition = types.find(item => item.id === selected);
  const canWrite = canManage && definition?.organization_id === organization && (
    project ? definition.project_id === project : definition.workspace_id === workspace && !definition.project_id
  );
  const path = { organization_id: organization, type_id: selected };

  useEffect(() => {
    let alive = true;
    void api.GET(typesPath, { params: { path: { organization_id: organization }, query: { workspace_id: workspace, ...(project ? { project_id: project } : {}) } } }).then(result => {
      if (alive && result.data) { setTypes(result.data.items); setTypeCursor(result.data.next_cursor); setSelected(result.data.items[0]?.id ?? ''); }
    }).catch(() => { if (alive) setMessage('Master data could not be loaded.'); });
    return () => { alive = false; };
  }, [api, organization, workspace, project]);

  useEffect(() => {
    setRecords([]); setPreview(undefined); setUpload(undefined); setCursor(null); setPendingStatus(undefined);
    if (!selected) return;
    let alive = true;
    void api.GET(recordsPath, { params: { path } }).then(result => {
      if (alive && result.data) { setRecords(result.data.items); setCursor(result.data.next_cursor); }
    }).catch(() => { if (alive) setMessage('Records could not be loaded.'); });
    return () => { alive = false; };
  }, [api, organization, selected]);

  async function run(action: () => Promise<void>) {
    setBusy(true); setMessage('');
    try { await action(); } catch { setMessage('The operation could not be completed. Check values and access, then retry.'); }
    finally { setBusy(false); }
  }

  async function createType(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const values = new FormData(form);
    await run(async () => {
      const result = await api.POST(typesPath, { params: { path: { organization_id: organization } }, body: {
        code: String(values.get('code')), name: String(values.get('name')), scope: project ? 'project' : 'workspace',
        workspace_id: workspace, project_id: project || null, registry: String(values.get('registry')) as components['schemas']['RegistryKind'],
        definition: { fields },
      } });
      if (!result.data) throw new Error('denied');
      setTypes(items => [...items, result.data]); setSelected(result.data.id); setFields([]); form.reset(); setMessage('Master data type created.');
    });
  }

  async function createRecord(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!definition) return;
    const form = event.currentTarget;
    const values = new FormData(form);
    await run(async () => {
      const dynamic = recordValues(definition.definition.fields ?? [], values);
      const result = await api.POST(recordsPath, { params: { path }, body: {
        code: String(values.get('code')), name: String(values.get('name')), status: 'active', values: { fields: dynamic },
        valid_from: String(values.get('valid-from')) || null, valid_until: String(values.get('valid-until')) || null,
      } });
      if (!result.data) throw new Error('denied');
      setRecords(items => [...items, result.data]); form.reset(); setMessage('Master data record created.');
    });
  }

  async function previewImport(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!definition) return;
    const input = new FormData(event.currentTarget).get('file');
    if (!(input instanceof File) || !input.size) return;
    setPreview(undefined); setUpload(undefined);
    await run(async () => {
      if (input.size > 4 * 1024 * 1024) throw new Error('size limit');
      const bytes = new Uint8Array(await input.arrayBuffer());
      let binary = '';
      for (let index = 0; index < bytes.length; index += 8192) binary += String.fromCharCode(...bytes.subarray(index, index + 8192));
      const uploaded = { data: btoa(binary), format: input.name.toLowerCase().endsWith('.xlsx') ? 'xlsx' as const : 'csv' as const };
      const result = await api.POST('/api/v1/organizations/{organization_id}/master-data/types/{type_id}/imports', {
        params: { path }, body: { content_base64: uploaded.data, format: uploaded.format, expected_type_version: definition.version, dry_run: true },
      });
      if (!result.data) throw new Error('denied');
      setPreview(result.data); setUpload(uploaded); setMessage('Import preview ready. No records have been written.');
    });
  }

  async function applyImport() {
    if (!preview || !upload || !definition) return;
    await run(async () => {
      const result = await api.POST('/api/v1/organizations/{organization_id}/master-data/types/{type_id}/imports', {
        params: { path }, body: { content_base64: upload.data, format: upload.format, expected_type_version: definition.version,
          expected_sha256: preview.source_sha256, dry_run: false },
      });
      if (!result.data) throw new Error('denied');
      const refreshed = await api.GET(recordsPath, { params: { path } });
      if (refreshed.data) { setRecords(refreshed.data.items); setCursor(refreshed.data.next_cursor); }
      setPreview(undefined); setUpload(undefined); setMessage('Import applied.');
    });
  }

  async function moreRecords() {
    if (!cursor) return;
    await run(async () => {
      const result = await api.GET(recordsPath, { params: { path, query: { cursor } } });
      if (!result.data) throw new Error('denied');
      setRecords(items => [...items, ...result.data.items]); setCursor(result.data.next_cursor);
    });
  }

  async function moreTypes() {
    if (!typeCursor) return;
    await run(async () => {
      const result = await api.GET(typesPath, { params: { path: { organization_id: organization }, query: { workspace_id: workspace, ...(project ? { project_id: project } : {}), cursor: typeCursor } } });
      if (!result.data) throw new Error('denied');
      setTypes(items => [...items, ...result.data.items]); setTypeCursor(result.data.next_cursor);
    });
  }

  async function exportRecords(format: 'csv' | 'xlsx') {
    await run(async () => {
      let next: string | undefined;
      let page = 1;
      do {
        const result = await api.GET('/api/v1/organizations/{organization_id}/master-data/types/{type_id}/export', {
          params: { path, query: { format, ...(next ? { cursor: next } : {}) } }, parseAs: 'blob',
        });
        if (!(result.data instanceof Blob)) throw new Error('denied');
        const url = URL.createObjectURL(result.data);
        const anchor = document.createElement('a'); anchor.href = url; anchor.download = `master-data-${page}.${format}`; anchor.click();
        URL.revokeObjectURL(url); next = result.response.headers.get('X-Next-Cursor') ?? undefined; page += 1;
      } while (next);
      setMessage('Export generated with stable record IDs and codes.');
    });
  }

  function changeField(index: number, changes: Partial<DataField>) {
    setFields(items => items.map((item, current) => current === index ? { ...item, ...changes } : item));
  }

  async function applyStatus() {
    if (!pendingStatus) return;
    const { record, status } = pendingStatus;
    await run(async () => {
      const result = await api.PUT('/api/v1/organizations/{organization_id}/master-data/types/{type_id}/records/{record_id}', {
        params: { path: { ...path, record_id: record.id } }, body: {
          name: record.name, status, valid_from: record.valid_from ?? null, valid_until: record.valid_until ?? null,
          values: record.values ?? { fields: {} }, expected_version: record.version,
        },
      });
      if (!result.data) throw new Error('denied');
      setRecords(items => items.map(item => item.id === result.data.id ? result.data : item)); setPendingStatus(undefined);
      setMessage('Record status updated. Historical references preserved.');
    });
  }

  return <section><h2>Master data</h2><p>Current scope: {project ? 'selected project' : 'selected workspace'}. Global references are read-only.</p>
    <p role="status" aria-live="polite">{message}</p>
    <label>Master data type<select aria-label="Master data type" disabled={busy} value={selected} onChange={event => setSelected(event.target.value)}>
      <option value="">Choose a type</option>{types.map(item => <option key={item.id} value={item.id}>{item.name} ({item.scope})</option>)}
    </select></label>{typeCursor && <button disabled={busy} onClick={() => void moreTypes()}>Load more types</button>}
    {canManage && <details><summary>Create a master data type</summary><form onSubmit={event => void createType(event)}>
      <label>Type code<input name="code" required pattern="[A-Za-z0-9][A-Za-z0-9_.-]{0,59}" /></label>
      <label>Type name<input name="name" required maxLength={120} /></label>
      <label>Registry<select name="registry"><option value="custom">Custom</option><option value="location">Locations</option><option value="asset">Assets</option><option value="unit">Units</option><option value="currency">Currencies</option><option value="shift">Shifts</option></select></label>
      {fields.map((field, index) => <fieldset key={index}><legend>Field {index + 1}</legend>
        <label>Field key<input value={field.key} required pattern="[a-z][a-z0-9_]{0,39}" onChange={event => changeField(index, { key: event.target.value })} /></label>
        <label>Field type<select value={field.kind} onChange={event => changeField(index, { kind: event.target.value as DataField['kind'], choices: [], reference_type_id: null })}>
          {['text', 'integer', 'decimal', 'boolean', 'date', 'enum', 'reference'].map(kind => <option key={kind}>{kind}</option>)}
        </select></label><label>Required<input type="checkbox" checked={field.required ?? false} onChange={event => changeField(index, { required: event.target.checked })} /></label>
        {field.kind === 'enum' && <label>Allowed values, separated by commas<input required value={field.choices?.join(',') ?? ''} onChange={event => changeField(index, { choices: event.target.value.split(',').map(item => item.trim()) })} /></label>}
        {field.kind === 'reference' && <label>Referenced type ID<input required value={field.reference_type_id ?? ''} onChange={event => changeField(index, { reference_type_id: event.target.value })} /></label>}
        <button type="button" onClick={() => setFields(items => items.filter((_, current) => current !== index))}>Remove field {index + 1}</button>
      </fieldset>)}
      <button type="button" disabled={fields.length >= 50} onClick={() => setFields(items => [...items, { key: '', kind: 'text', required: false }])}>Add field</button>
      <p>Review fields before creation. Changing a schema requires a new type; existing records keep their original schema.</p><button disabled={busy}>Create type</button>
    </form></details>}
    {definition && <><h3>{definition.name}</h3><table><thead><tr><th>Code</th><th>Name</th><th>Status</th></tr></thead>
      <tbody>{records.map(record => <tr key={record.id}><td>{record.code}</td><td>{record.name}</td><td>{canWrite ?
        <select aria-label={`Status for ${record.code}`} value={record.status} disabled={busy} onChange={event => setPendingStatus({ record, status: event.target.value as Record['status'] })}>
          <option>active</option><option>inactive</option><option>deprecated</option>
        </select> : record.status}</td></tr>)}</tbody></table>
      {pendingStatus && <div><p>Review {pendingStatus.record.code}: {pendingStatus.record.status} → {pendingStatus.status}. Inactive or deprecated records cannot be selected for new references; existing history stays intact.</p>
        <button disabled={busy} onClick={() => void applyStatus()}>Apply record status</button><button disabled={busy} onClick={() => setPendingStatus(undefined)}>Cancel status change</button>
      </div>}
      {cursor && <button disabled={busy} onClick={() => void moreRecords()}>Load more records</button>}
      <button disabled={busy} onClick={() => void exportRecords('csv')}>Export CSV</button><button disabled={busy} onClick={() => void exportRecords('xlsx')}>Export XLSX</button>
    </>}
    {canWrite && definition && <><form onSubmit={event => void createRecord(event)}><h3>Create a record</h3>
      <label>Record code<input name="code" required pattern="[A-Za-z0-9][A-Za-z0-9_.-]{0,59}" /></label><label>Record name<input name="name" required maxLength={120} /></label>
      <label>Valid from<input name="valid-from" type="date" /></label><label>Valid until<input name="valid-until" type="date" /></label>
      {(definition.definition.fields ?? []).map(field => <label key={field.key}>{field.key}{field.kind === 'enum' ?
        <select name={'value-' + field.key} required={field.required}><option value="">Choose a value</option>{field.choices?.map(choice => <option key={choice}>{choice}</option>)}</select> :
        <input name={'value-' + field.key} type={field.kind === 'boolean' ? 'checkbox' : field.kind === 'date' ? 'date' : 'text'}
          required={field.kind !== 'boolean' && field.required} maxLength={2000} />}</label>)}<button disabled={busy}>Create record</button>
    </form><form onSubmit={event => void previewImport(event)}><h3>Import records</h3><p>CSV or XLSX; up to 1,000 rows and 4 MiB. Headers: code, name, status, valid_from, valid_until, then field keys. Imports add records and reject duplicate codes.</p>
      <label>Import file<input type="file" name="file" accept=".csv,.xlsx" required onChange={() => { setPreview(undefined); setUpload(undefined); }} /></label><button disabled={busy}>Preview import</button>
    </form>{preview && <div><p>{preview.rows.length} valid rows; {preview.issues.length} issues.</p>
      <ul>{preview.issues.map((issue, index) => <li key={index}>Row {issue.row}: {issue.code.replaceAll('_', ' ')}</li>)}</ul>
      <table><thead><tr><th>Code</th><th>Name</th></tr></thead><tbody>{preview.rows.map(record => <tr key={record.id}><td>{record.code}</td><td>{record.name}</td></tr>)}</tbody></table>
      <button disabled={busy || !!preview.issues.length || !preview.rows.length} onClick={() => void applyImport()}>Apply import</button>
    </div>}</>}
  </section>;
}
