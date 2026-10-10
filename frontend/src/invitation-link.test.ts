import { describe, expect, it } from 'vitest';
import { invitationPath, invitationRequestId, invitationTargetFromState, readInvitationTarget } from './invitation-link';

const target = { organization: '019cc949-bd93-7cf4-b5ed-c7225082ad00', invitation: '019cc949-bd93-7cf4-b5ed-c7225082ad01' };

describe('token-free invitation links', () => {
  it('preserves only public invitation IDs through PKCE state', () => {
    expect(readInvitationTarget(invitationPath(target).slice(1))).toEqual(target);
    expect(invitationTargetFromState({ invitation: target, redirect: 'https://evil.test', token: 'secret' })).toEqual(target);
    expect(invitationPath(target)).not.toContain('token');
  });
  it('rejects malformed and ambiguous targets rather than trusting URL redirects', () => {
    for (const state of [null, 'https://evil.test', { invitation: 'x' }, { invitation: { ...target, organization: 'https://evil.test' } }]) {
      expect(invitationTargetFromState(state)).toBeUndefined();
    }
    expect(readInvitationTarget('?organization=x&invitation=y')).toBeUndefined();
    expect(readInvitationTarget(invitationPath(target).slice(1) + '&organization=' + target.organization)).toBeUndefined();
  });
  it('creates unique UUIDv7 request IDs with timestamp and RFC variant', () => {
    const first = invitationRequestId(); const second = invitationRequestId();
    expect(first).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    expect(first).not.toEqual(second);
    expect(Math.abs(parseInt(first.replaceAll('-', '').slice(0, 12), 16) - Date.now())).toBeLessThan(1000);
  });
});
