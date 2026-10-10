import { useEffect, useRef, useState } from 'react';
import type { components } from './api-schema';
import type { apiClient } from './client';
import { canReplayWebhook } from './webhook-status';

type Delivery = components['schemas']['WebhookDeliveryView'];
type History = components['schemas']['WebhookDeliveryHistory'];
type Review = components['schemas']['WebhookDeliveryReview'];
const base = '/api/v1/organizations/{organization_id}/webhook-deliveries' as const;
const detailPath = `${base}/{delivery_id}` as const;
const states: Delivery['state'][] = ['pending', 'sending', 'sent', 'retry', 'uncertain', 'failed', 'skipped'];
function failure(error: unknown): string {
  return error && typeof error === 'object' && 'code' in error ? String(error.code) : 'Webhook evidence could not be loaded.';
}

export function WebhookRecovery({ api, organization }: { api: ReturnType<typeof apiClient>; organization: string }) {
  const path = { organization_id: organization };
  const [state, setState] = useState<Delivery['state'] | ''>('');
  const [deliveries, setDeliveries] = useState<Delivery[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [history, setHistory] = useState<History>();
  const [review, setReview] = useState<Review>();
  const [reason, setReason] = useState('');
  const [acknowledged, setAcknowledged] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const generation = useRef(0);
  function clearEvidence() { setHistory(undefined); setReview(undefined); setReason(''); setAcknowledged(false); }
  async function run(work: () => Promise<void>) {
    setBusy(true); setMessage('');
    try { await work(); } catch (error) { setMessage(error instanceof Error ? error.message : failure(error)); }
    finally { setBusy(false); }
  }
  async function loadPage(after?: string) {
    if (!after) { generation.current++; clearEvidence(); }
    const ticket = generation.current;
    const result = await api.GET(base, { params: { path, query: { state: state || null, cursor: after ?? null } } });
    if (ticket !== generation.current) return;
    if (!result.data) throw new Error(failure(result.error));
    setDeliveries(current => after ? [...current, ...result.data.items] : result.data.items);
    setCursor(result.data.next_cursor ?? null);
  }
  async function loadHistory(id: string) {
    const ticket = ++generation.current; clearEvidence();
    const result = await api.GET(detailPath, { params: { path: { ...path, delivery_id: id } } });
    if (ticket !== generation.current) return;
    if (!result.data) throw new Error(failure(result.error)); setHistory(result.data);
  }
  useEffect(() => {
    const ticket = ++generation.current; setDeliveries([]); setCursor(null); clearEvidence(); setBusy(true); setMessage('');
    void api.GET(base, { params: { path, query: { state: state || null } } }).then(result => {
      if (ticket !== generation.current) return;
      if (result.data) { setDeliveries(result.data.items); setCursor(result.data.next_cursor ?? null); }
      else setMessage(failure(result.error));
    }).catch(() => { if (ticket === generation.current) setMessage('Webhook evidence could not be loaded.'); })
      .finally(() => { if (ticket === generation.current) setBusy(false); });
    return () => { generation.current++; };
  }, [api, organization, state]);
  async function replay(apply: boolean) {
    if (!history || (apply && !review)) return;
    const ticket = generation.current;
    await run(async () => {
      const result = await api.POST(`${detailPath}/replay`, {
        params: { path: { ...path, delivery_id: history.delivery.id } },
        body: { dry_run: !apply, review_sha256: apply ? review?.review_sha256 ?? null : null,
          reason: apply ? reason : null, acknowledge_uncertain: apply && acknowledged },
      });
      if (ticket !== generation.current) return;
      if (!result.data) throw new Error(failure(result.error));
      if (apply) {
        const row = result.data.delivery;
        setDeliveries(current => current.map(item => item.id === row.id ? row : item).filter(item => !state || item.state === state));
        await loadHistory(row.id); setMessage('Webhook queued for reviewed replay. Previous attempts are preserved.');
      } else { setReview(result.data); setAcknowledged(false); setMessage('Replay preview ready. Review the outcome and provide a reason.'); }
    });
  }
  return <section aria-label="Webhook delivery and recovery">
    <h2>Webhook delivery and recovery</h2><p>History contains identifiers and outcomes only; request bodies, URLs and signing secrets are excluded.</p>
    <p role="status">{message}</p>
    <label>Webhook delivery status<select aria-label="Webhook delivery status" value={state} disabled={busy} onChange={event => setState(event.target.value as Delivery['state'] | '')}><option value="">All statuses</option>{states.map(item => <option key={item}>{item}</option>)}</select></label>
    <button disabled={busy} onClick={() => void run(() => loadPage())}>Refresh webhook deliveries</button>
    {cursor && <button disabled={busy} onClick={() => void run(() => loadPage(cursor))}>More webhook deliveries</button>}
    {!busy && !deliveries.length && <p>No webhook deliveries in this view.</p>}
    <ul>{deliveries.map(row => <li key={row.id}><button disabled={busy} onClick={() => void run(() => loadHistory(row.id))}>{row.state} — {row.id} — endpoint {row.endpoint_id} v{row.endpoint_version} — {row.attempts} attempts</button></li>)}</ul>
    {history && <><h3>Webhook delivery evidence</h3><p>Delivery {history.delivery.id}: {history.delivery.state}</p>
      <p>Endpoint {history.delivery.endpoint_id} version {history.delivery.endpoint_version}; created {history.delivery.created_at}; next check {history.delivery.next_at}; error {history.delivery.error_code ?? 'none'}.</p>
      <ul>{history.attempts.map(row => <li key={row.number}>Attempt {row.number}: {row.outcome} — {row.error_code ?? 'none'} — {row.started_at} to {row.finished_at}</li>)}</ul>
      {history.delivery.state === 'sending' && <p>An expired send claim becomes uncertain. Refresh after the worker records the outcome.</p>}
      <button disabled={busy} onClick={() => void run(() => loadHistory(history.delivery.id))}>Refresh webhook evidence</button>
      {canReplayWebhook(history.delivery) && <button disabled={busy} onClick={() => void replay(false)}>Preview webhook replay</button>}
      {review && <><p>Reviewed {review.delivery.state} after {review.delivery.attempts} attempts. Review {review.review_sha256}.</p>
        <label>Webhook replay reason<input value={reason} maxLength={500} disabled={busy} onChange={event => setReason(event.target.value)}/></label>
        {review.delivery.state === 'uncertain' && <><p>The remote endpoint may already have accepted this request. Replay can cause a duplicate.</p><label><input type="checkbox" checked={acknowledged} disabled={busy} onChange={event => setAcknowledged(event.target.checked)}/>I reviewed the uncertain outcome and accept possible duplicate delivery</label></>}
        <button disabled={busy || !reason.trim() || (review.delivery.state === 'uncertain' && !acknowledged)} onClick={() => void replay(true)}>Apply webhook replay</button>
      </>}
    </>}
  </section>;
}
