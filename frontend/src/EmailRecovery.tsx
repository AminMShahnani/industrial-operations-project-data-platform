import { useEffect, useRef, useState } from 'react';
import type { components } from './api-schema';
import type { apiClient } from './client';
import { canReplayEmail, emailStatus } from './email-status';
type Delivery = components['schemas']['EmailDelivery'];
type History = components['schemas']['EmailHistory'];
type Review = components['schemas']['EmailReview'];
const base = '/api/v1/organizations/{organization_id}/email-deliveries' as const;
const detailPath = `${base}/{delivery_id}` as const;
const states: Delivery['state'][] = ['pending', 'sending', 'sent', 'retry', 'uncertain', 'failed', 'skipped'];
function failure(error: unknown): string { return error && typeof error === 'object' && 'code' in error ? String(error.code) : 'Email evidence could not be loaded.'; }

export function EmailRecovery({ api, organization }: { api: ReturnType<typeof apiClient>; organization: string }) {
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
  async function run(work: () => Promise<void>) { setBusy(true); setMessage(''); try { await work(); } catch (error) { setMessage(error instanceof Error ? error.message : failure(error)); } finally { setBusy(false); } }
  async function loadPage(after?: string) {
    if (!after) { generation.current++; clearEvidence(); }
    const ticket = generation.current;
    const result = await api.GET(base, { params: { path, query: { state: state || null, cursor: after ?? null } } });
    if (ticket !== generation.current) return;
    if (!result.data) throw new Error(failure(result.error)); setDeliveries(current => after ? [...current, ...result.data.items] : result.data.items); setCursor(result.data.next_cursor ?? null);
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
      if (result.data) { setDeliveries(result.data.items); setCursor(result.data.next_cursor ?? null); } else setMessage(failure(result.error));
    }).catch(() => { if (ticket === generation.current) setMessage('Email evidence could not be loaded.'); }).finally(() => { if (ticket === generation.current) setBusy(false); });
    return () => { generation.current++; };
  }, [api, organization, state]);
  async function replay(apply: boolean) {
    if (!history || (apply && !review)) return; const ticket = generation.current;
    await run(async () => {
      const result = await api.POST(`${detailPath}/replay`, { params: { path: { ...path, delivery_id: history.delivery.id } }, body: { dry_run: !apply, review_sha256: apply ? review?.review_sha256 ?? null : null, reason: apply ? reason : null, acknowledge_uncertain: apply && acknowledged } });
      if (ticket !== generation.current) return;
      if (!result.data) throw new Error(failure(result.error));
      if (apply) { const row = result.data.delivery; setDeliveries(current => current.map(item => item.id === row.id ? row : item).filter(item => !state || item.state === state)); await loadHistory(row.id); setMessage('Email queued for reviewed replay. Previous attempts are preserved.'); }
      else { setReview(result.data); setAcknowledged(false); setMessage('Replay preview ready. Review the outcome and provide a reason.'); }
    });
  }
  return <section aria-label="Email delivery and recovery">
    <h2>Email delivery and recovery</h2><p>Evidence for the selected organization. SMTP provider acceptance does not prove mailbox delivery.</p><p role="status">{message}</p>
    <label>Email delivery status<select aria-label="Email delivery status" value={state} disabled={busy} onChange={event => setState(event.target.value as Delivery['state'] | '')}><option value="">All statuses</option>{states.map(item => <option key={item} value={item}>{emailStatus(item)}</option>)}</select></label>
    <button disabled={busy} onClick={() => void run(() => loadPage())}>Refresh email deliveries</button>{cursor && <button disabled={busy} onClick={() => void run(() => loadPage(cursor))}>More email deliveries</button>}
    {!busy && !deliveries.length && <p>No email deliveries in this view.</p>}
    <ul>{deliveries.map(row => <li key={row.id}><button disabled={busy} onClick={() => void run(() => loadHistory(row.id))}>{emailStatus(row.state)} — {row.source_kind} — {row.id} — {row.attempts} attempts</button></li>)}</ul>
    {history && <><h3>Email delivery evidence</h3><p>Delivery {history.delivery.id}: {emailStatus(history.delivery.state)}</p>
      <p>Source {history.delivery.source_kind}: {history.delivery.source_id}; recipient ID {history.delivery.recipient_id ?? 'invited member'}; original operator {history.delivery.operator_id}.</p>
      <p>Created {history.delivery.created_at}; next check {history.delivery.next_at}; {history.delivery.attempts} attempts; error {history.delivery.error_code ?? 'none'}; correlation {history.delivery.correlation_id}.</p>
      <ul>{history.attempts.map(row => <li key={row.id}>Email attempt {row.number}: {emailStatus(row.outcome)} — {row.error_code ?? 'none'} — {row.occurred_at}</li>)}</ul>
      {history.delivery.state === 'sending' && <p>The worker resolves expired send claims as uncertain. Refresh after recovery; an in-progress send cannot be replayed here.</p>}
      <button disabled={busy} onClick={() => void run(() => loadHistory(history.delivery.id))}>Refresh email evidence</button>
      {canReplayEmail(history.delivery) && <button disabled={busy} onClick={() => void replay(false)}>Preview email replay</button>}
      {review && <><p>Reviewed {emailStatus(review.delivery.state)} at {review.delivery.attempts} attempts. Review {review.review_sha256}.</p>
        <label>Email replay reason<input value={reason} maxLength={500} disabled={busy} onChange={event => setReason(event.target.value)}/></label>
        {review.delivery.state === 'uncertain' && <><p>The provider may already have accepted this message. Replay can send a duplicate.</p><label><input type="checkbox" checked={acknowledged} disabled={busy} onChange={event => setAcknowledged(event.target.checked)}/>I reviewed the uncertain outcome and accept possible duplicate delivery</label></>}
        <button disabled={busy || !reason.trim() || (review.delivery.state === 'uncertain' && !acknowledged)} onClick={() => void replay(true)}>Apply email replay</button>
      </>}
    </>}
  </section>;
}
