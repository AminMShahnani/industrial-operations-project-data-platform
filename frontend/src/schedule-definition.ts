import type { components } from './api-schema';
type Definition = components['schemas']['ScheduleDefinition'];
function record(value: unknown): value is Record<string, unknown> { return typeof value === 'object' && value !== null && !Array.isArray(value); }
export function parseSchedule(source: string): Definition {
  if (source.length > 65536) throw new Error('Schedule definition exceeds 64 KiB.');
  const value: unknown = JSON.parse(source);
  if (!record(value) || typeof value.form_id !== 'string' || !Number.isInteger(value.form_number) || !record(value.recurrence) || typeof value.recurrence.kind !== 'string'
    || !Array.isArray(value.assignments) || !value.assignments.length || value.assignments.length > 30
    || !value.assignments.every(item => record(item) && ['user','team','department','role','shift'].includes(String(item.kind)))) throw new Error('Invalid schedule definition.');
  return value as Definition; // Only request data; server validates every typed property before persistence.
}
