import type { components } from './api-schema';
type Delivery = components['schemas']['EmailDelivery'];
export function emailStatus(state: Delivery['state']): string {
  return { pending: 'Queued', sending: 'Send in progress', sent: 'Accepted by SMTP provider', retry: 'Waiting for retry', uncertain: 'Outcome uncertain', failed: 'Failed', skipped: 'Skipped' }[state];
}
export function canReplayEmail(delivery: Pick<Delivery, 'state' | 'attempts'>): boolean { return ['retry', 'failed', 'uncertain'].includes(delivery.state) && delivery.attempts < 20; }
