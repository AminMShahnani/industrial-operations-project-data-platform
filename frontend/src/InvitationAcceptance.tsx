import { useState, type FormEvent } from 'react';
import type { apiClient } from './client';
import type { InvitationTarget } from './invitation-link';

export function InvitationAcceptance({ api, target, onAccepted }: {
  api: ReturnType<typeof apiClient>; target: InvitationTarget | undefined;
  onAccepted: (organization: string) => Promise<void>;
}) {
  const [organization, setOrganization] = useState(target?.organization ?? '');
  const [invitation, setInvitation] = useState(target?.invitation ?? '');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  async function accept(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setMessage('');
    try {
      const result = await api.POST('/api/v1/organizations/{organization_id}/invitations/verified-email/{invitation_id}/accept', {
        params: { path: { organization_id: organization, invitation_id: invitation } },
      });
      if (result.data) {
        setMessage('Sign-in invitation accepted.');
        setInvitation('');
        window.history.replaceState({}, '', '/');
        await onAccepted(organization);
      } else setMessage('Invitation unavailable. Sign in with the invited verified email, or contact the inviter.');
    } catch { setMessage('The platform could not be reached.'); }
    finally { setBusy(false); }
  }
  return <section aria-label="Sign-in invitation"><h2>Accept a sign-in invitation</h2>
    <p>Your verified sign-in email must match the invited email. Review the organization before accepting.</p>
    <form onSubmit={event => void accept(event)}>
      <label>Invited organization ID<input value={organization} onChange={event => setOrganization(event.target.value)} required /></label>
      <label>Sign-in invitation ID<input value={invitation} onChange={event => setInvitation(event.target.value)} required /></label>
      <button disabled={busy}>Accept sign-in invitation</button>
    </form><p role="status">{message}</p>
  </section>;
}
