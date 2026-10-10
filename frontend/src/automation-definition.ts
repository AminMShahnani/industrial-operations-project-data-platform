import type { components } from './api-schema';
type Definition = components['schemas']['AutomationCreate']['definition'];
export const metadataStarter: Definition = { trigger: 'project.phase.changed', actions: [{ kind: 'set_metadata', description: 'Project phase changed.' }] };
export function parseAutomationDefinition(text: string): Definition {
  const value: unknown = JSON.parse(text);
  if (!value || typeof value !== 'object' || !('trigger' in value) || typeof value.trigger !== 'string' || !('actions' in value) || !Array.isArray(value.actions) || value.actions.length < 1 || value.actions.length > 20) throw new Error('Enter a declarative trigger and one to twenty actions.');
  for (const action of value.actions as unknown[]) if (!action || typeof action !== 'object' || !('kind' in action) || typeof action.kind !== 'string') throw new Error('Each action needs a kind.');
  // The server validates the complete schema, permissions and supported handlers.
  return value as Definition;
}
