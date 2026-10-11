import { useEffect, useState, type FormEvent } from 'react';
import type { components } from './api-schema';
import type { apiClient } from './client';

type Client = ReturnType<typeof apiClient>;
type Registry = components['schemas']['RegistrySnapshot'];
type Installation = components['schemas']['PackInstallation'];
type Plan = components['schemas']['LifecyclePlan'];
type Operation = components['schemas']['LifecycleOperation'];
const base = '/api/v1/organizations/{organization_id}/domain-packs' as const;

export function DomainPacks({ api, organization, canManage }: { api: Client; organization: string; canManage: boolean }) {
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
  const path = { organization_id: organization };

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
  </section>;
}
