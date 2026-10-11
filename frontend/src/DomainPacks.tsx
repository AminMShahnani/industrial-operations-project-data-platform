import { useEffect, useState, type FormEvent } from 'react';
import type { components } from './api-schema';
import type { apiClient } from './client';

type Client = ReturnType<typeof apiClient>;
type Registry = components['schemas']['RegistrySnapshot'];
type Installation = components['schemas']['PackInstallation'];
type Plan = components['schemas']['LifecyclePlan'];
type Operation = components['schemas']['LifecycleOperation'];
type CatalogArtifacts = components['schemas']['PackArtifactCatalogPage'];
type ImportPreview = components['schemas']['operations__modules__domain_packs__application__imports__ImportPreview'];
type ImportedArtifact = components['schemas']['ArtifactImportResult'];
const base = '/api/v1/organizations/{organization_id}/domain-packs' as const;
const workspaceBase = '/api/v1/organizations/{organization_id}/workspaces/{workspace_id}' as const;

export function DomainPacks({ api, organization, workspace, permissions, canManage }: { api: Client; organization: string; workspace?: string; permissions: string[]; canManage: boolean }) {
  const [registry, setRegistry] = useState<Registry>();
  const [installations, setInstallations] = useState<Installation[]>([]);
  const [operation, setOperation] = useState<Operation>('install');
  const [selected, setSelected] = useState('');
  const [versionRange, setVersionRange] = useState('>=1.0.0');
  const [plan, setPlan] = useState<Plan>();
  const [reason, setReason] = useState('');
  const [confirmBreaking, setConfirmBreaking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [artifacts, setArtifacts] = useState<CatalogArtifacts['items']>([]);
  const [artifactId, setArtifactId] = useState('');
  const [projectId, setProjectId] = useState('');
  const [projects, setProjects] = useState<{ id: string; name: string }[]>([]);
  const [importPreview, setImportPreview] = useState<ImportPreview>();
  const [importedArtifact, setImportedArtifact] = useState<ImportedArtifact>();
  const [importKey, setImportKey] = useState('');
  const path = { organization_id: organization };

  useEffect(() => {
    if (!workspace) { setProjects([]); setProjectId(''); return; }
    let alive = true;
    void api.GET(`${workspaceBase}/projects`, { params: { path: { organization_id: organization, workspace_id: workspace } } })
      .then(result => { if (alive && result.data) setProjects(result.data.items.map(item => ({ id: item.id, name: item.name }))); })
      .catch(() => { if (alive) setMessage('Workspace projects could not be loaded.'); });
    return () => { alive = false; };
  }, [api, organization, workspace]);

  async function loadArtifacts(packId: string, version: string) {
    setImportPreview(undefined); setArtifacts([]); setArtifactId('');
    const result = await api.GET(`${base}/catalog/{pack_id}/{version}/artifacts`, {
      params: { path: { ...path, pack_id: packId, version } },
    });
    if (result.data) setArtifacts(result.data.items);
  }

  async function previewArtifactImport() {
    const release = installations.find(item => item.pack_id === selected && item.state !== 'disabled' && item.state !== 'uninstalled');
    const artifact = artifacts.find(item => item.artifact_id === artifactId);
    if (!workspace || !release || !artifact) return;
    const key = crypto.randomUUID();
    setImportKey(key); setBusy(true); setMessage('');
    try {
      const result = await api.POST(`${base}/imports/preview`, { params: { path }, body: {
        pack_id: release.pack_id, pack_version: release.version,
        artifact_id: artifact.artifact_id, artifact_version: artifact.artifact_version,
        workspace_id: workspace, ...(projectId ? { project_id: projectId } : {}), idempotency_key: key,
      } });
      if (result.data) { setImportPreview(result.data); setMessage('Review the artifact and target scope before importing.'); }
      else setMessage('The artifact preview could not be created.');
    } catch { setMessage('The artifact is unavailable or your scoped permission does not allow this import.'); }
    finally { setBusy(false); }
  }

  async function applyArtifactImport() {
    if (!importPreview?.valid || !importPreview.preview_sha256 || !importKey) return;
    setBusy(true); setMessage('');
    try {
      const result = await api.POST(`${base}/imports`, { params: { path }, body: {
        pack_id: importPreview.pack_id, pack_version: importPreview.pack_version,
        artifact_id: importPreview.artifact_id, artifact_version: importPreview.artifact_version,
        workspace_id: importPreview.workspace_id,
        ...(importPreview.project_id ? { project_id: importPreview.project_id } : {}),
        idempotency_key: importKey, expected_preview_sha256: importPreview.preview_sha256,
      } });
      if (result.data) { setImportedArtifact(result.data); setMessage(importedMessage(result.data)); setImportPreview(undefined); }
      else setMessage('The import did not complete. Create a fresh preview.');
    } catch { setMessage('The preview expired or is no longer authorized. Create a new preview.'); }
    finally { setBusy(false); }
  }

  async function refresh() {
    const [catalog, installed] = await Promise.all([
      api.GET(`${base}/catalog`, { params: { path } }),
      api.GET(`${base}/installations`, { params: { path } }),
    ]);
    if (catalog.data) {
      setRegistry(catalog.data);
        const firstRelease = (catalog.data.releases ?? [])[0];
        if (!selected && firstRelease) setSelected(firstRelease.manifest.id);
    }
    if (installed.data) setInstallations(installed.data.items);
  }

  useEffect(() => {
    let alive = true;
    void Promise.all([
      api.GET(`${base}/catalog`, { params: { path } }),
      api.GET(`${base}/installations`, { params: { path } }),
    ]).then(([catalog, installed]) => {
      if (!alive) return;
      if (catalog.data) {
        setRegistry(catalog.data);
        const firstRelease = (catalog.data.releases ?? [])[0];
        if (firstRelease) setSelected(firstRelease.manifest.id);
      }
      if (installed.data) setInstallations(installed.data.items);
      if (!catalog.data || !installed.data) setMessage('Pack catalog or installations could not be loaded.');
    }).catch(() => { if (alive) setMessage('The pack service could not be reached.'); });
    return () => { alive = false; };
  }, [api, organization]);

  async function preview(event: FormEvent) {
    event.preventDefault();
    if (!selected) return;
    setBusy(true); setMessage(''); setPlan(undefined);
    try {
      const result = await api.POST(`${base}/plans`, {
        params: { path },
        body: { operation, pack_id: selected, ...(operation === 'install' || operation === 'upgrade' ? { version_range: versionRange } : {}) },
      });
      if (result.data) {
        setPlan(result.data);
        setMessage(result.data.valid ? 'Review this plan before applying it.' : (result.data.issues ?? []).map(issue => issue.message).join(' '));
      } else setMessage('The plan could not be created.');
    } catch { setMessage('The plan service could not be reached.'); }
    finally { setBusy(false); }
  }

  async function apply() {
    if (!plan?.valid || !plan.plan_sha256 || !reason.trim()) return;
    setBusy(true); setMessage('');
    try {
      const result = await api.POST(`${base}/apply`, {
        params: { path },
        body: {
          operation: plan.operation,
          pack_id: plan.pack_id,
          ...(plan.operation === 'install' || plan.operation === 'upgrade' ? { version_range: versionRange } : {}),
          expected_plan_sha256: plan.plan_sha256,
          reason: reason.trim(),
          confirm_breaking_change: confirmBreaking,
        },
      });
      if (result.data) {
        setInstallations(result.data.items); setPlan(undefined); setReason(''); setConfirmBreaking(false);
        setMessage('Pack lifecycle operation completed and audited.');
      } else setMessage('The plan could not be applied. Review the current installation state.');
    } catch { setMessage('The plan is stale or could not be applied. Create a new preview.'); }
    finally { setBusy(false); }
  }

  const releases = (registry?.releases ?? []).filter(item => item.manifest.id === selected) ?? [];
  const current = installations.find(item => item.pack_id === selected);
  return <section aria-labelledby="domain-packs-heading">
    <h2 id="domain-packs-heading">Domain Packs</h2>
    <p>Organization-scoped packs come from the curated registry. Review a dry-run plan before applying any lifecycle change.</p>
    {message && <p role="status">{message}</p>}
    {registry && !registry.valid && <p role="alert">The curated registry is invalid; pack operations are unavailable.</p>}
    {(registry?.releases ?? []).length === 0 && registry && <p>The curated registry has no available releases.</p>}
    {registry && (registry.releases ?? []).length > 0 && <>
      <form onSubmit={event => void preview(event)}>
        <label>Pack<select value={selected} onChange={event => { setSelected(event.target.value); setPlan(undefined); }}>
          {[...new Set((registry.releases ?? []).map(item => item.manifest.id))].map(id => <option key={id} value={id}>{id}</option>)}
        </select></label>
        <label>Operation<select value={operation} onChange={event => { setOperation(event.target.value as Operation); setPlan(undefined); }}>
          {(['install', 'upgrade', 'enable', 'disable', 'uninstall'] as const).map(value => <option key={value} value={value}>{value}</option>)}
        </select></label>
        {(operation === 'install' || operation === 'upgrade') && <label>Version range<input value={versionRange} maxLength={128} onChange={event => setVersionRange(event.target.value)} required /></label>}
        <p>{current ? `Installed ${current.version} (${current.state})` : 'Not installed'}</p>
        <ul>{releases.map(item => <li key={item.manifest.version}>{item.manifest.name} Â· {item.manifest.version} Â· {item.content_sha256}</li>)}</ul>
        {canManage && <button disabled={busy || !selected || registry.valid === false}>Preview plan</button>}
        <button type="button" disabled={busy} onClick={() => void refresh()}>Refresh</button>
      </form>
      {plan && <div aria-label="Domain Pack plan review">
        <h3>{plan.valid ? 'Plan ready for review' : 'Plan cannot be applied'}</h3>
        <ul>{(plan.steps ?? []).map((step, index) => <li key={`${step.pack_id}-${index}`}>{step.action}: {step.pack_id}{step.from_version ? ` ${step.from_version} -> ${step.to_version}` : step.to_version ? ` ${step.to_version}` : ''}</li>)}</ul>
        {(plan.selected_release_summaries ?? []).map(release => <p key={`${release.pack_id}-${release.version}`}>{release.pack_id}@{release.version} | SHA-256 {release.content_sha256}</p>)}
        {(plan.steps ?? []).some(step => step.requires_breaking_review) && <label><input type="checkbox" checked={confirmBreaking} onChange={event => setConfirmBreaking(event.target.checked)} />Confirm reviewed major-version change</label>}
        {plan.valid && canManage && <>
          <label>Reason for change<input value={reason} maxLength={500} onChange={event => setReason(event.target.value)} required /></label>
          <button disabled={busy || !reason.trim() || ((plan.steps ?? []).some(step => step.requires_breaking_review) && !confirmBreaking)} onClick={() => void apply()}>Apply reviewed plan</button>
        </>}
      </div>}
    </>}
    <h3>Organization installations</h3>
    {installations.length ? <ul>{installations.map(item => <li key={item.id}>{item.pack_id}@{item.version} | {item.state} | {item.content_sha256}</li>)}</ul> : <p>No packs installed.</p>}
    {workspace && <section aria-labelledby="pack-import-heading">
      <h3 id="pack-import-heading">Import a pack artifact</h3>
      <p>Review an installed artifact and its target scope. Forms and workflows remain drafts; automation templates stay inert, and mapping profiles are internal metadata without transform execution.</p>
      {current && current.state !== 'disabled' && current.state !== 'uninstalled' && <button type="button" disabled={busy} onClick={() => void loadArtifacts(current.pack_id, current.version)}>Load installed artifacts</button>}
      <label htmlFor="domain-pack-artifact">Artifact<select id="domain-pack-artifact" aria-label="Artifact" value={artifactId} onChange={event => { setArtifactId(event.target.value); setImportPreview(undefined); }}>
        <option value="">Choose an artifact</option>
        {artifacts.map(item => <option key={`${item.kind}-${item.artifact_id}-${item.artifact_version}`} value={item.artifact_id}>{item.name} ({item.kind})</option>)}
      </select></label>
      <label>Target project<select value={projectId} onChange={event => { setProjectId(event.target.value); setImportPreview(undefined); }}>
        <option value="">Workspace</option>{projects.map(project => <option key={project.id} value={project.id}>{project.name}</option>)}
      </select></label>
      {artifactId && <button type="button" disabled={busy} onClick={() => void previewArtifactImport()}>Preview artifact import</button>}
      {importPreview && <div aria-label="Domain Pack artifact import review">
        <h4>Review import</h4>
        <p>{importPreview.name} · {importPreview.artifact_kind} · {importPreview.pack_id}@{importPreview.pack_version}</p>
        <p>Target: {projects.find(project => project.id === importPreview.project_id)?.name ?? 'Workspace'} · SHA-256 {importPreview.package_sha256}</p>
        {importPreview.artifact_kind === 'workflow' && <p>The workflow remains a draft; import its referenced form first.</p>}
        {importPreview.artifact_kind === 'kpi' && <p>This creates a private saved report pinned to the published source form version. KPI reads require scoped submission.read.</p>}
        {importPreview.artifact_kind === 'automation_template' && <p>This is an inert catalog import. It does not create or activate an automation rule.</p>}
        {importPreview.artifact_kind === 'mapping_profile' && <p>This stores an internal version-neutral mapping profile. No external standard conformance or transforms are applied.</p>}
        <button type="button" disabled={busy || !canImportKind(importPreview.artifact_kind, permissions)} onClick={() => void applyArtifactImport()}>Import reviewed artifact</button>
      </div>}
      {importedArtifact && <section aria-label="Imported artifact details"><h4>Imported artifact details</h4><p>{importedMessage(importedArtifact)}</p>{importedArtifact.inert_definition && <pre>{JSON.stringify(importedArtifact.inert_definition, null, 2)}</pre>}</section>}
    </section>}
  </section>;
}

function canImportKind(kind: string | null | undefined, permissions: string[]): boolean {
  if (kind === 'mapping_profile') {
    return permissions.includes('workspace.read') || permissions.includes('project.read');
  }
  const required = kind === 'form' ? 'form.manage'
    : kind === 'master_data_type' ? 'master_data.manage'
      : kind === 'workflow' ? 'workflow.manage'
        : kind === 'automation_template' ? 'automation.manage'
          : kind === 'kpi' ? 'submission.read' : '';
  return Boolean(required && permissions.includes(required));
}

function importedMessage(result: ImportedArtifact): string {
  return `Imported ${result.artifact_id} as ${result.artifact_kind} (${result.target_id}).`;
}
