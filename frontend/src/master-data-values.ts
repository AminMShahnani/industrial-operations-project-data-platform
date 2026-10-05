import type { components } from './api-schema';

export function recordValues(fields: components['schemas']['DataField'][], form: FormData) {
  const values: { [key: string]: string | number | boolean | null } = {};
  for (const field of fields) {
    const value = String(form.get('value-' + field.key) ?? '');
    if (field.kind === 'boolean') values[field.key] = form.get('value-' + field.key) === 'on';
    else if (!value) values[field.key] = null;
    else if (field.kind === 'integer') {
      if (!/^-?\d+$/.test(value)) throw new Error('Enter a whole number.');
      const integer = Number(value);
      if (!Number.isSafeInteger(integer)) throw new Error('Use a decimal field for values beyond safe integer precision.');
      values[field.key] = integer;
    } else values[field.key] = value;
  }
  return values;
}
