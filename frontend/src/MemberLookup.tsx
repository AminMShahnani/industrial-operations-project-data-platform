import { useEffect, useRef, useState } from 'react';
import type { components } from './api-schema';
import type { apiClient } from './client';

export function MemberLookup({ api, organization, workspace, scope, onSelect }: {
  api: ReturnType<typeof apiClient>; organization: string; workspace: string;
  scope: { kind: 'project' | 'group'; id: string }; onSelect: (id: string) => void;
}) {
  const [email, setEmail] = useState('');
  const [members, setMembers] = useState<components['schemas']['User'][]>([]);
  const [selected, setSelected] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const generation = useRef(0);
  useEffect(() => () => { generation.current += 1; }, [api, organization, workspace, scope.kind, scope.id]);
  async function find() {
    const request = ++generation.current;
    setBusy(true); setMessage(''); setMembers([]); setSelected(''); onSelect('');
    try {
      const result = scope.kind === 'project' ? await api.GET('/api/v1/organizations/{organization_id}/workspaces/{workspace_id}/projects/{project_id}/membership-candidates', {
        params: { path: { organization_id: organization, workspace_id: workspace, project_id: scope.id }, query: { email } },
      }) : await api.GET('/api/v1/organizations/{organization_id}/workspaces/{workspace_id}/groups/{group_id}/membership-candidates', {
        params: { path: { organization_id: organization, workspace_id: workspace, group_id: scope.id }, query: { email } },
      });
      if (request !== generation.current) return;
      if (!result.data) throw new Error('denied');
      setMembers(result.data.items);
      const first = result.data.items[0]?.id ?? ''; setSelected(first); onSelect(first);
      setMessage(first ? 'Review the matching organization member before granting access.' : 'No active organization member matches that email.');
    } catch { if (request === generation.current) setMessage('Member lookup could not be completed.'); }
    finally { if (request === generation.current) setBusy(false); }
  }
  return <fieldset><legend>Find an existing organization member</legend>
    <label>Member email<input type="email" value={email} onChange={event => { generation.current += 1; setBusy(false); setEmail(event.target.value); setMembers([]); setSelected(''); onSelect(''); }} /></label>
    <button type="button" disabled={busy || !email} onClick={() => void find()}>Find member</button>
    <p role="status">{message}</p>
    <label>Matching member<select disabled={busy} value={selected} onChange={event => { setSelected(event.target.value); onSelect(event.target.value); }}>
      <option value="">Choose a member</option>{members.map(member => <option key={member.id} value={member.id}>{member.email}{members.length > 1 ? ` (${member.subject})` : ''}</option>)}
    </select></label>
  </fieldset>;
}
