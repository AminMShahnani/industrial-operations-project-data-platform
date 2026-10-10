import { expect, it } from 'vitest';
import { canReplayWebhook } from './webhook-status';

it('allows only bounded retryable or reviewed uncertain webhook outcomes', () => {
  for (const state of ['pending', 'sending', 'sent', 'skipped'] as const) {
    expect(canReplayWebhook({ state, attempts: 1 })).toBe(false);
  }
  for (const state of ['retry', 'failed', 'uncertain'] as const) {
    expect(canReplayWebhook({ state, attempts: 19 })).toBe(true);
    expect(canReplayWebhook({ state, attempts: 20 })).toBe(false);
  }
});
