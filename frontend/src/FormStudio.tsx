import { useEffect, useRef, useState, type FormEvent } from 'react';
import type { components } from './api-schema';
import type { apiClient } from './client';
import { RuntimeFields, editableValues } from './FormRuntime';
import { parseComponent, parseDefinition } from './form-definition';

type Client = ReturnType<typeof apiClient>;
type Form = components['schemas']['Form'];
type Version = components['schemas']['FormVersion'];
type Definition = components['schemas']['FormDefinition-Input'];
type Field = components['schemas']['Component-Input'];
type Submission = components['schemas']['Submission'];
type Result = components['schemas']['RuntimeResult'];
type Values = Record<string, components['schemas']['Value']>;
const base = '/api/v1/organizations/{organization_id}/workspaces/{workspace_id}' as const;
const formsPath = `${base}/forms` as const;
const versionsPath = `${base}/forms/{form_id}/versions` as const;
const versionPath = `${versionsPath}/{number}` as const;
const draftsPath = `${base}/submissions` as const;
const draftPath = `${draftsPath}/{submission_id}` as const;
const kinds: Field['kind'][] = ['text', 'textarea', 'integer', 'decimal', 'boolean', 'date', 'datetime', 'time', 'select', 'multi_select', 'radio', 'user', 'department', 'project', 'master_data', 'file', 'image', 'signature', 'calculated', 'table', 'repeating_group', 'display'];
function errorCode(value: unknown): string {
  return value && typeof value === 'object' && 'code' in value && typeof value.code === 'string' ? value.code : 'Request rejected.';
}
const initial: Definition = { schema_version: 1, sections: [{ key: 'main', label: 'Main', components: [] }] };

export function FormStudio({ api, organization, workspace, project, canManage, canManageLibrary, taskForm, taskDraft, onSubmitted }: {
  api: Client; organization: string; workspace: string; project: string; canManage: boolean; canManageLibrary: boolean; taskForm?: string | undefined; taskDraft?: string | undefined; onSubmitted?: ((id:string)=>void)|undefined;
}) {
  const [libraries, setLibraries] = useState<components['schemas']['LibraryArtifact'][]>([]);
  const [library, setLibrary] = useState('');
  const [libraryCursor, setLibraryCursor] = useState<string | null>(null);
  const [forms, setForms] = useState<Form[]>([]);
  const [form, setForm] = useState(taskForm ?? '');
  const [versions, setVersions] = useState<Version[]>([]);
  const [number, setNumber] = useState(1);
  const [definition, setDefinition] = useState<Definition>(initial);
  const [section, setSection] = useState(0);
  const [field, setField] = useState(-1);
  const [advanced, setAdvanced] = useState('');
  const [pendingLifecycle, setPendingLifecycle] = useState<'deprecated' | 'retired'>();
  const [preview, setPreview] = useState<Version>();
  const [runtime, setRuntime] = useState<Result>();
  const [values, setValues] = useState<Values>({});
  const [draft, setDraft] = useState<Submission>();
  const [draftCursor, setDraftCursor] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Submission[]>([]);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [cursor, setCursor] = useState<string | null>(null);
  const [versionCursor, setVersionCursor] = useState<string | null>(null);
  const dirty = useRef(false);
  const autosavePending = useRef(false);
  const locked = useRef(false);
  const key = useRef<string>(crypto.randomUUID());
  const loadedTask = useRef('');
  const path = { organization_id: organization, workspace_id: workspace };
  const version = versions.find(item => item.number === number);
  const fields = definition.sections[section]?.components ?? [];
  const selected = fields[field];
  const editable = canManage && version?.state === 'draft';
  const allFields = definition.sections.flatMap(item => item.components ?? []);

  useEffect(() => {
    let active = true;
    if (canManage) void api.GET(`${base}/form-library`, { params: { path: { organization_id: organization, workspace_id: workspace }, query: { ...(project ? { project_id: project } : {}) } } }).then(result => {
      if (active && result.data) { setLibraries(result.data.items); setLibraryCursor(result.data.next_cursor); }
    }).catch(() => { if (active) setMessage('Libraries could not be loaded.'); });
    return () => { active = false; };
  }, [api, organization, workspace, project, canManage]);

  useEffect(() => {
    let active = true;
    void api.GET(formsPath, { params: { path: { organization_id: organization, workspace_id: workspace }, query: { ...(project ? { project_id: project } : {}) } } }).then(result => {
      if (active && result.data) { setForms(result.data.items); setCursor(result.data.next_cursor); setForm(taskForm ?? result.data.items[0]?.id ?? ''); }
    }).catch(() => { if (active) setMessage('Forms could not be loaded.'); });
    return () => { active = false; };
  }, [api, organization, workspace, project, taskForm]);

  useEffect(() => {
    let active = true;
    setVersions([]); setDraft(undefined); setRuntime(undefined); setPreview(undefined); dirty.current = false;
    if (form) {
      void api.GET(versionsPath, { params: { path: { organization_id: organization, workspace_id: workspace, form_id: form } } }).then(result => {
        if (active && result.data) { setVersions(result.data.items); setVersionCursor(result.data.next_cursor); setNumber(result.data.items.at(-1)?.number ?? 1); }
      }).catch(() => { if (active) setMessage('Versions could not be loaded.'); });
      void api.GET(`${formsPath}/{form_id}/submissions`, { params: { path: { organization_id: organization, workspace_id: workspace, form_id: form } } }).then(result => { if (active && result.data) { setDrafts(result.data.items); setDraftCursor(result.data.next_cursor); } }).catch(() => { if (active) setMessage('Drafts could not be loaded.'); });
    }
    return () => { active = false; };
  }, [api, organization, workspace, form]);

  useEffect(() => {
    if (version) { setDefinition(version.definition); setSection(0); setField(-1); setValues(draft?.form_version_id === version.id ? (draft.values.fields ?? {}) : {}); setRuntime(undefined); setPreview(undefined); setPendingLifecycle(undefined); }
  }, [version]);

  useEffect(() => { setAdvanced(selected ? JSON.stringify(selected, null, 2) : ''); }, [selected]);

  useEffect(() => {
    if (taskDraft && taskForm === form && versions.length && loadedTask.current !== taskDraft) {
      loadedTask.current = taskDraft;
      void loadDraft(taskDraft);
    }
  }, [taskDraft, taskForm, form, versions.length]);

  function updateField(changes: Partial<Field>) {
    setDefinition(current => ({ ...current, sections: current.sections.map((item, index) => index === section ? { ...item, components: (item.components ?? []).map((component, position) => position === field ? { ...component, ...changes } : component) } : item) }));
    setPreview(undefined);
  }
  async function action(work: () => Promise<void>) {
    if (locked.current) return;
    locked.current = true; setBusy(true); setMessage('');
    try { await work(); } catch { setMessage('Request failed. Refresh or retry after checking your connection.'); }
    finally { locked.current = false; setBusy(false); }
  }
  function updateVersion(updated: Version) { setVersions(current => current.map(item => item.id === updated.id ? updated : item)); }
  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const data = new FormData(event.currentTarget);
    await action(async () => {
      const result = await api.POST(formsPath, { params: { path }, body: { name: String(data.get('name')), definition, ...(project ? { project_id: project } : {}) } });
      if (result.data) { setForms(current => [...current, result.data]); setForm(result.data.id); setMessage('Form draft created.'); } else setMessage(errorCode(result.error));
    });
  }
  async function saveDefinition() {
    if (!version) return;
    await action(async () => {
      const result = await api.PUT(versionPath, { params: { path: { ...path, form_id: form, number } }, body: { definition, expected_revision: version.revision } });
      if (result.data) { updateVersion(result.data); setMessage('Definition saved.'); } else setMessage(errorCode(result.error));
    });
  }
  async function publish(apply: boolean) {
    if (!version) return;
    await action(async () => {
      const result = await api.POST(`${versionPath}/publish`, { params: { path: { ...path, form_id: form, number } }, body: { expected_revision: version.revision, dry_run: !apply, ...(apply && preview?.content_sha256 ? { expected_sha256: preview.content_sha256 } : {}) } });
      if (result.data) { if (apply) { updateVersion(result.data); setPreview(undefined); setMessage('Version published.'); } else { setPreview(result.data); setMessage('Publication validated. Review the snapshot before publishing.'); } } else setMessage(errorCode(result.error));
    });
  }
  async function clone() {
    await action(async () => {
      const result = await api.POST(versionsPath, { params: { path: { ...path, form_id: form } }, body: { source_number: number, number: Math.max(...versions.map(item => item.number)) + 1 } });
      if (result.data) { setVersions(current => [...current, result.data]); setNumber(result.data.number); } else setMessage(errorCode(result.error));
    });
  }
  async function newDraft() {
    await action(async () => {
      const result = await api.POST(draftsPath, { params: { path }, body: { form_id: form, number } });
      if (result.data) { setDraft(result.data); setValues(result.data.values.fields ?? {}); setRuntime(result.data.initialization); dirty.current = false; autosavePending.current = false; setDrafts(current => [...current, result.data]); key.current = crypto.randomUUID(); setMessage('Submission draft created.'); } else setMessage(errorCode(result.error));
    });
  }
  async function validate() {
    await action(async () => {
      const body = { values: { fields: editableValues(allFields, values, canManage) }, complete: true };
      const result = draft ? await api.POST(`${draftPath}/validate`, { params: { path: { ...path, submission_id: draft.id } }, body })
        : await api.POST(`${versionPath}/preview`, { params: { path: { ...path, form_id: form, number } }, body });
      if (result.data) { setRuntime(result.data); setMessage(result.data.issues.length ? 'Please correct the highlighted fields.' : 'Validation passed.'); } else setMessage(errorCode(result.error));
    });
  }
  async function saveDraft() {
    if (!draft || draft.state !== 'draft') return;
    autosavePending.current = false;
    await action(async () => {
      const result = await api.PUT(draftPath, { params: { path: { ...path, submission_id: draft.id } }, body: { values: { fields: editableValues(allFields, values, canManage) }, expected_revision: draft.revision } });
      if (result.data) { setDraft(result.data); setDrafts(current => current.map(item => item.id === result.data.id ? result.data : item)); dirty.current = false; setMessage('Draft saved.'); } else setMessage(errorCode(result.error));
    });
  }
  useEffect(() => {
    if (!draft || draft.state !== 'draft' || !dirty.current || !autosavePending.current || busy) return;
    const timer = window.setTimeout(() => { void saveDraft(); }, 1200);
    return () => window.clearTimeout(timer);
  });
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const data = new FormData(event.currentTarget);
    if (!draft || dirty.current) { setMessage('Save your draft before submitting.'); return; }
    await action(async () => {
      const result = await api.POST(`${draftPath}/submit`, { params: { path: { ...path, submission_id: draft.id } }, body: { expected_revision: draft.revision, idempotency_key: key.current, reason: String(data.get('reason')) } });
      if (result.data) { setDraft(result.data); setDrafts(current => current.map(item => item.id === result.data.id ? result.data : item)); setValues(result.data.values.fields ?? {}); onSubmitted?.(result.data.id); setMessage('Submission preserved as an immutable snapshot.'); } else setMessage(errorCode(result.error));
    });
  }
  async function upload(key: string, file: File) {
    if (!draft) return;
    await action(async () => {
      if (file.size > 5 * 1024 * 1024) { setMessage('Attachment exceeds 5 MiB.'); return; }
      const bytes = new Uint8Array(await file.arrayBuffer()); let binary = '';
      for (let index = 0; index < bytes.length; index += 8192) binary += String.fromCharCode(...bytes.subarray(index, index + 8192));
      const contentType = file.type;
      if (!['text/plain', 'application/pdf', 'image/png', 'image/jpeg'].includes(contentType)) { setMessage('Unsupported attachment type.'); return; }
      const result = await api.POST(`${draftPath}/files`, { params: { path: { ...path, submission_id: draft.id } }, body: { name: file.name, content_type: contentType as 'text/plain' | 'application/pdf' | 'image/png' | 'image/jpeg', content_base64: btoa(binary) } });
      if (result.data) { setValues(current => {
        const nested = /^([a-z][a-z0-9_]*)\[(\d+)\]\.([a-z][a-z0-9_]*)$/.exec(key);
        if (!nested) return { ...current, [key]: result.data.id };
        const rows = current[nested[1] ?? ''];
        if (!Array.isArray(rows) || !rows.every(row => row !== null && typeof row === 'object')) return current;
        return { ...current, [nested[1] ?? '']: rows.map((row, index) => index === Number(nested[2]) ? { ...row, [nested[3] ?? '']: result.data.id } : row) };
      }); dirty.current = true; autosavePending.current = true; setMessage('Attachment scanned and uploaded.'); } else setMessage(errorCode(result.error));
    });
  }
  async function loadDraft(identifier: string) {
    if (!identifier) { setDraft(undefined); setRuntime(undefined); dirty.current = false; return; }
    await action(async () => {
      const result = await api.GET(draftPath, { params: { path: { ...path, submission_id: identifier } } });
      if (!result.data) { setMessage(errorCode(result.error)); return; }
      const exact = await api.GET(versionPath, { params: { path: { ...path, form_id: result.data.form_id, number: result.data.form_number } } });
      if (!exact.data) { setMessage(errorCode(exact.error)); return; }
      setVersions(current => [...current.filter(item => item.id !== exact.data.id), exact.data]); setNumber(exact.data.number);
      setDraft(result.data); setValues(result.data.values.fields ?? {}); setRuntime(undefined); dirty.current = false; key.current = result.data.submit_key ?? crypto.randomUUID();
      if (result.data.state === 'submitted') onSubmitted?.(result.data.id);
    });
  }
  async function download(identifier: string) {
    await action(async () => {
      const result = await api.POST(`${base}/files/{file_id}/download`, { params: { path: { ...path, file_id: identifier } } });
      if (!result.data) { setMessage(errorCode(result.error)); return; }
      const link = document.createElement('a'); link.href = result.data.url; link.rel = 'noreferrer'; link.download = ''; link.click();
    });
  }
  function attachments(): string[] {
    const result: string[] = [];
    function visit(fields: Field[], current: Values) { for (const field of fields) {
      const value = current[field.key];
      if (['file', 'image'].includes(field.kind) && typeof value === 'string') result.push(value);
      else if (field.children?.length && Array.isArray(value)) for (const row of value) if (row && typeof row === 'object') visit(field.children, row);
    } }
    visit(allFields, values); return [...new Set(result)];
  }
  async function moreForms() { if (!cursor) return; await action(async () => { const result = await api.GET(formsPath, { params: { path, query: { cursor, ...(project ? { project_id: project } : {}) } } }); if (result.data) { setForms(current => [...current, ...result.data.items]); setCursor(result.data.next_cursor); } }); }
  async function moreVersions() { if (!versionCursor) return; await action(async () => { const result = await api.GET(versionsPath, { params: { path: { ...path, form_id: form }, query: { cursor: versionCursor } } }); if (result.data) { setVersions(current => [...current, ...result.data.items]); setVersionCursor(result.data.next_cursor); } }); }
  return <section aria-label="Form Studio"><h2>Form Studio</h2><p>{project ? 'Project forms' : 'Workspace forms'} ? Definitions are immutable after publication.</p>
    {message && <p role="status">{message.replaceAll('_', ' ')}</p>}
    <label>Form<select aria-label="Form" disabled={busy} value={form} onChange={event => setForm(event.target.value)}><option value="">Choose a form</option>{forms.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
    {cursor && <button disabled={busy} onClick={() => void moreForms()}>Load more forms</button>}
    {form && <><label>Version<select disabled={busy} value={number} onChange={event => { setNumber(Number(event.target.value)); setDraft(undefined); dirty.current = false; }}>
      {versions.map(item => <option key={item.id} value={item.number}>{item.number} ? {item.state}</option>)}</select></label>{versionCursor && <button disabled={busy} onClick={() => void moreVersions()}>Load more versions</button>}
      {canManage && <button disabled={busy || !version} onClick={() => void clone()}>Create next version</button>}</>}
    {(editable || (!form && canManage)) && <fieldset disabled={busy}><legend>Builder</legend>
      <label>Import JSON definition<input type="file" accept="application/json,.json" onChange={event => { const file = event.target.files?.[0]; if (!file) return; void action(async () => { if (file.size > 1024 * 1024) { setMessage('Definition exceeds 1 MiB.'); return; } try { setDefinition(parseDefinition(JSON.parse(await file.text()) as unknown)); setSection(0); setField(-1); setPreview(undefined); setMessage('Definition loaded for review; no server data changed.'); } catch { setMessage('Invalid form definition file.'); } }); }} /></label>
      <label>Reusable library<select aria-label="Reusable library" value={library} onChange={event => setLibrary(event.target.value)}><option value="">Choose a pinned artifact</option>{libraries.map(item => <option key={item.id} value={item.id}>{item.code} ? {item.version} ? {item.kind}</option>)}</select></label>
      {library && <button type="button" onClick={() => { const artifact = libraries.find(item => item.id === library); if (!artifact) return; if (artifact.kind === 'form') { setDefinition(artifact.definition); setSection(0); setField(-1); } else setDefinition(current => ({ ...current, sections: current.sections.map((item, index) => index === section ? { ...item, references: [...(item.references ?? []), { artifact_id: artifact.id, version: artifact.version }] } : item) })); setPreview(undefined); }}>Use pinned library artifact</button>}
      {libraryCursor && <button type="button" onClick={() => void action(async () => { const result = await api.GET(`${base}/form-library`, { params: { path, query: { cursor: libraryCursor, ...(project ? { project_id: project } : {}) } } }); if (result.data) { setLibraries(current => [...current, ...result.data.items]); setLibraryCursor(result.data.next_cursor); } })}>Load more libraries</button>}
      <label>Section<select value={section} onChange={event => { setSection(Number(event.target.value)); setField(-1); }}>{definition.sections.map((item, index) => <option key={index} value={index}>{item.label}</option>)}</select></label>
      <button type="button" disabled={definition.sections.length >= 30} onClick={() => setDefinition(current => ({ ...current, sections: [...current.sections, { key: `section_${current.sections.length + 1}`, label: `Section ${current.sections.length + 1}`, components: [] }] }))}>Add section</button>
      <label>Section label<input value={definition.sections[section]?.label ?? ''} onChange={event => setDefinition(current => ({ ...current, sections: current.sections.map((item, index) => index === section ? { ...item, label: event.target.value } : item) }))} /></label>
      <form onSubmit={event => { event.preventDefault(); const data = new FormData(event.currentTarget); const kind = String(data.get('kind')) as Field['kind']; const next: Field = { key: `field_${allFields.length + 1}`, kind, label: 'New field', required: false, ...(kind === 'calculated' ? { formula: { op: 'literal', value: '0' } } : {}), ...(['select', 'multi_select', 'radio'].includes(kind) ? { choices: ['Option 1'] } : {}), ...(['table', 'repeating_group'].includes(kind) ? { children: [{ key: 'item', label: 'Item', kind: 'text', required: false }] } : {}) }; setDefinition(current => ({ ...current, sections: current.sections.map((item, index) => index === section ? { ...item, components: [...(item.components ?? []), next] } : item) })); setField(fields.length); }}>
        <label>Component palette<select name="kind" aria-label="Component palette">{kinds.map(kind => <option key={kind}>{kind}</option>)}</select></label><button disabled={allFields.length >= 100}>Add component</button>
      </form>
      {(definition.sections[section]?.references ?? []).map((pin, index) => <p key={index}>Pinned artifact {libraries.find(item => item.id === pin.artifact_id)?.code ?? pin.artifact_id} ? {pin.version}<button type="button" onClick={() => setDefinition(current => ({ ...current, sections: current.sections.map((item, position) => position === section ? { ...item, references: (item.references ?? []).filter((_, ordinal) => ordinal !== index) } : item) }))}>Remove reference</button></p>)}
      <ol>{fields.map((item, index) => <li key={index}><button type="button" onClick={() => setField(index)} aria-pressed={field === index}>{item.label} ({item.kind})</button><button type="button" disabled={index === 0} onClick={() => { setDefinition(current => ({ ...current, sections: current.sections.map((entry, position) => { if (position !== section) return entry; const reordered = [...(entry.components ?? [])]; [reordered[index - 1], reordered[index]] = [reordered[index]!, reordered[index - 1]!]; return { ...entry, components: reordered }; }) })); setField(index - 1); }}>Move {item.label} up</button></li>)}</ol>
      {selected && <fieldset><legend>Properties</legend><label>Stable field key<input value={selected.key} onChange={event => updateField({ key: event.target.value })} /></label><label>Field label<input value={selected.label} onChange={event => updateField({ label: event.target.value })} /></label><label>Required<input type="checkbox" checked={selected.required ?? false} onChange={event => updateField({ required: event.target.checked })} /></label>
        {['select', 'multi_select', 'radio'].includes(selected.kind) && <label>Choices (one per line)<textarea value={selected.choices?.join('\n') ?? ''} onChange={event => updateField({ choices: event.target.value.split('\n') })} /></label>}
        <label>Advanced declarative properties<textarea rows={12} value={advanced} onChange={event => setAdvanced(event.target.value)} /></label><button type="button" onClick={() => { try { const parsed: unknown = JSON.parse(advanced); if (!parsed || typeof parsed !== 'object') throw new Error(); updateField(parseComponent(parsed)); setMessage('Properties updated; server validation is required.'); } catch { setMessage('Properties must be a JSON component object.'); } }}>Apply properties</button>
        <button type="button" onClick={() => { setDefinition(current => ({ ...current, sections: current.sections.map((item, index) => index === section ? { ...item, components: (item.components ?? []).filter((_, position) => position !== field) } : item) })); setField(-1); }}>Remove component</button>
      </fieldset>}
      {canManageLibrary && <form onSubmit={event => { event.preventDefault(); const data = new FormData(event.currentTarget); void action(async () => {
        const kind = String(data.get('artifact_kind')) as 'field' | 'component' | 'form';
        const content: Definition = kind === 'field' && selected ? { schema_version: 1, sections: [{ key: 'library', label: 'Library', components: [selected] }] } : kind === 'component' ? { schema_version: 1, sections: [definition.sections[section] ?? { key: 'main', label: 'Main', components: [] }] } : definition;
        const result = await api.POST(`${base}/form-library`, { params: { path }, body: { code: String(data.get('code')), version: Number(data.get('artifact_version')), kind, definition: content } });
        if (result.data) { setLibraries(current => [...current, result.data]); setMessage('Immutable library version published.'); } else setMessage(errorCode(result.error));
      }); }}><label>Library code<input name="code" required maxLength={60} /></label><label>Library version<input name="artifact_version" type="number" min={1} defaultValue={1} required /></label><label>Library kind<select name="artifact_kind"><option value="form">Form template</option><option value="component">Section template</option><option value="field">Selected field</option></select></label><button>Publish library version</button></form>}
      {!form ? <form onSubmit={event => void create(event)}><label>Form name<input name="name" required maxLength={120} /></label><button>Create form draft</button></form> : <button onClick={() => void saveDefinition()}>Save definition</button>}
    </fieldset>}
    {editable && <><button disabled={busy} onClick={() => void publish(false)}>Preview publication</button>{preview && <><pre>{JSON.stringify(preview.definition, null, 2)}</pre><button disabled={busy} onClick={() => void publish(true)}>Publish reviewed version</button></>}</>}
    {canManage && version && version.state !== 'draft' && version.state !== 'retired' && <>
      <button disabled={busy} onClick={() => setPendingLifecycle(version.state === 'published' ? 'deprecated' : 'retired')}>Preview {version.state === 'published' ? 'deprecation' : 'retirement'}</button>
      {pendingLifecycle && <form onSubmit={event => { event.preventDefault(); const data = new FormData(event.currentTarget); void action(async () => {
        const result = await api.POST(`${versionPath}/lifecycle`, { params: { path: { ...path, form_id: form, number } }, body: { state: pendingLifecycle, expected_revision: version.revision, dry_run: false, reason: String(data.get('lifecycle_reason')) } });
        if (result.data) { updateVersion(result.data); setPendingLifecycle(undefined); } else setMessage(errorCode(result.error));
      }); }}><p>{pendingLifecycle === 'deprecated' ? 'New submissions will be blocked; existing drafts may continue.' : 'All draft writes will stop. Historical submissions remain readable.'}</p><label>Form lifecycle reason<input name="lifecycle_reason" required maxLength={500} /></label><button disabled={busy}>Apply reviewed lifecycle change</button></form>}
    </>}
    {version && <section><h3>Runtime preview and submission</h3>{version.state === 'published' && !draft && <button disabled={busy} onClick={() => void newDraft()}>Start submission draft</button>}
      <label>My saved drafts<select aria-label="My saved drafts" disabled={busy} value={draft?.id ?? ''} onChange={event => void loadDraft(event.target.value)}><option value="">Choose</option>{drafts.map(item => <option key={item.id} value={item.id}>{item.id} ? {item.state}</option>)}</select></label>
      {draftCursor && <button disabled={busy} onClick={() => void action(async () => { const result = await api.GET(`${formsPath}/{form_id}/submissions`, { params: { path: { ...path, form_id: form }, query: { cursor: draftCursor } } }); if (result.data) { setDrafts(current => [...current, ...result.data.items]); setDraftCursor(result.data.next_cursor); } })}>Load more submissions</button>}
      {draft && attachments().map((id, index) => <button key={id} disabled={busy} onClick={() => void download(id)}>Download attachment {index + 1}</button>)}

      <fieldset disabled={busy || draft?.state === 'submitted'}><legend>{forms.find(item => item.id === form)?.name ?? 'Form'}</legend>
        {definition.sections.map(item => <fieldset key={item.key}><legend>{item.label}</legend><RuntimeFields fields={item.components ?? []} values={values} result={runtime} manager={canManage} disabled={busy || draft?.state === 'submitted'}
          change={updated => { setValues(updated); setRuntime(undefined); dirty.current = true; autosavePending.current = true; }} upload={draft ? upload : undefined} lookup={async (key, email, cursor) => {
            const response = await api.GET(`${versionPath}/lookups/{field_key}`, { params: { path: { ...path, form_id: form, number, field_key: key }, query: { ...(email ? { email } : {}), ...(cursor ? { cursor } : {}) } } });
            if (!response.data) throw new Error('Lookup denied'); return response.data;
          }} /></fieldset>)}
      </fieldset><button disabled={busy} onClick={() => void validate()}>Validate form</button>
      {draft?.state === 'draft' && <><button disabled={busy} onClick={() => void saveDraft()}>Save submission draft</button><form onSubmit={event => void submit(event)}><label>Submission reason<input name="reason" required maxLength={500} /></label><button disabled={busy}>Submit form</button></form><p>Draft autosaves after 1.2 seconds of inactivity. Submitted snapshots are immutable.</p></>}
    </section>}
  </section>;
}
