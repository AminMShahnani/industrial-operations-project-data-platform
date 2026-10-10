import type { components } from './api-schema';

type Delivery = components['schemas']['WebhookDeliveryView'];

export function canReplayWebhook(delivery: Pick<Delivery, 'state' | 'attempts'>): boolean {
  return ['retry', 'failed', 'uncertain'].includes(delivery.state) && delivery.attempts < 20;
}
