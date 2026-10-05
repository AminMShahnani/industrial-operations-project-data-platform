import type { components } from './api-schema';
type Field = components['schemas']['Component-Input'];
type Definition = components['schemas']['FormDefinition-Input'];
const kinds = new Set(['text', 'textarea', 'integer', 'decimal', 'boolean', 'date', 'datetime', 'time', 'select', 'multi_select', 'radio', 'user', 'department', 'project', 'master_data', 'file', 'image', 'signature', 'calculated', 'table', 'repeating_group', 'display']);
function object(value: unknown): value is Record<string, unknown> { return Boolean(value) && typeof value === 'object' && !Array.isArray(value); }
export function parseComponent(value: unknown, depth = 0): Field {
  if (!object(value) || typeof value.key !== 'string' || typeof value.label !== 'string' || typeof value.kind !== 'string' || !kinds.has(value.kind) || depth > 1) throw new Error('Invalid component');
  if (value.required !== undefined && typeof value.required !== 'boolean') throw new Error('Invalid required flag');
  if (value.choices !== undefined && (!Array.isArray(value.choices) || value.choices.length > 100 || !value.choices.every(choice => typeof choice === 'string'))) throw new Error('Invalid choices');
  if (value.children !== undefined) {
    if (!Array.isArray(value.children) || value.children.length > 30) throw new Error('Invalid children');
    value.children.forEach(child => parseComponent(child, depth + 1));
  }
  return { ...value, required: value.required ?? false } as Field;
}
export function parseDefinition(value: unknown): Definition {
  if (!object(value) || value.schema_version !== 1 || !Array.isArray(value.sections) || !value.sections.length || value.sections.length > 30) throw new Error('Invalid form definition');
  let total = 0;
  for (const section of value.sections) {
    if (!object(section) || typeof section.key !== 'string' || typeof section.label !== 'string') throw new Error('Invalid section');
    if (section.components !== undefined) {
      if (!Array.isArray(section.components)) throw new Error('Invalid components');
      total += section.components.length;
      if (total > 100) throw new Error('Too many components');
      section.components.forEach(component => parseComponent(component));
    }
    if (section.references !== undefined && (!Array.isArray(section.references) || section.references.length > 30 || !section.references.every(pin => object(pin) && typeof pin.artifact_id === 'string' && Number.isInteger(pin.version)))) throw new Error('Invalid library pins');
  }
  return value as Definition;
}
