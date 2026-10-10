import { expect, it } from 'vitest';
import { canReplayEmail, emailStatus } from './email-status';
it('describes SMTP acceptance without claiming mailbox delivery', () => {
  expect(emailStatus('sent')).toBe('Accepted by SMTP provider'); expect(emailStatus('uncertain')).toBe('Outcome uncertain');
});
it('allows recovery only for failed or uncertain outcomes within the lifetime bound', () => {
  for (const state of ['pending', 'sending', 'sent', 'skipped'] as const) expect(canReplayEmail({ state, attempts: 1 })).toBe(false);
  for (const state of ['retry', 'failed', 'uncertain'] as const) { expect(canReplayEmail({ state, attempts: 19 })).toBe(true); expect(canReplayEmail({ state, attempts: 20 })).toBe(false); }
});
