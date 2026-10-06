import { useEffect, useState } from 'react';
import type { components } from './api-schema';
import type { apiClient } from './client';

type Item = components['schemas']['InboxItem'];
const base = '/api/v1/organizations/{organization_id}/workspaces/{workspace_id}/notifications' as const;
const topics: Record<components['schemas']['Notice']['topic'], string> = {
  work_assigned: 'Work assigned', review_requested: 'Review requested', rule_notice: 'Operational notice',
};

export function Notifications({ api, organization, workspace }: {
  api: ReturnType<typeof apiClient>; organization: string; workspace: string;
}) {
  const [items, setItems] = useState<Item[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [generation, setGeneration] = useState(0);
  const path = { organization_id: organization, workspace_id: workspace };

  useEffect(() => {
    let active = true;
    setItems([]); setCursor(null); setMessage(''); setBusy(true);
    void api.GET(base, { params: { path } }).then(result => {
      if (!active) return;
      if (result.data) { setItems(result.data.items); setCursor(result.data.next_cursor); }
      else setMessage('Notifications could not be loaded. Check your access and refresh.');
    }).catch(() => { if (active) setMessage('Notifications could not be loaded.'); })
      .finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, [api, organization, workspace, generation]);

  async function more() {
    if (!cursor) return;
    setBusy(true); setMessage('');
    try {
      const result = await api.GET(base, { params: { path, query: { cursor } } });
      if (!result.data) throw new Error();
      setItems(current => [...current, ...result.data.items]); setCursor(result.data.next_cursor);
    } catch { setMessage('More notifications could not be loaded. Refresh to check current access.'); }
    finally { setBusy(false); }
  }

  async function read(item: Item) {
    setBusy(true); setMessage('');
    try {
      const result = await api.POST(`${base}/{notification_id}/read`, {
        params: { path: { ...path, notification_id: item.notice.id } },
      });
      if (!result.data) {
        // Clear previously displayed content after a failed fresh access check.
        setItems([]); setCursor(null); throw new Error();
      }
      setItems(current => current.map(row => row.notice.id === item.notice.id
        ? { ...row, read_at: result.data.read_at } : row));
      setMessage('Notification marked as read.');
    } catch { setMessage('Notification could not be read. Refresh to check current access.'); }
    finally { setBusy(false); }
  }

  return <section aria-labelledby="notifications-heading" aria-busy={busy}>
    <h2 id="notifications-heading">Notifications</h2>
    <p>Your notices for this workspace.</p>
    <button disabled={busy} onClick={() => setGeneration(value => value + 1)}>Refresh notifications</button>
    {message && <p role="status">{message}</p>}
    {!busy && items.length === 0 && !cursor && !message && <p>No notifications available.</p>}
    <ul>{items.map(item => <li key={item.notice.id}>
      <strong>{topics[item.notice.topic]}</strong>{' — '}{item.notice.source_kind}{' — '}
      <time dateTime={item.notice.created_at}>{new Date(item.notice.created_at).toLocaleString()}</time>{' — '}
      {item.read_at ? <span>Read</span> : <button disabled={busy} onClick={() => void read(item)}>Mark as read</button>}
    </li>)}</ul>
    {cursor && <button disabled={busy} onClick={() => void more()}>Load more notifications</button>}
  </section>;
}
