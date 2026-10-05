import { expect, it } from 'vitest';
import { parseComponent, parseDefinition } from './form-definition';
it('rejects unsafe imported shapes before rendering and preserves declarative definitions', () => {
  expect(() => parseDefinition({ schema_version: 1, sections: 'not-an-array' })).toThrow();
  expect(() => parseComponent({ key: 'x', label: { secret: true }, kind: 'text' })).toThrow();
  expect(() => parseComponent({ key: 'x', label: 'X', kind: 'python' })).toThrow();
  const component = parseComponent({ key: 'x', label: 'X', kind: 'integer' });
  expect(component.required).toBe(false);
  expect(parseDefinition({ schema_version: 1, sections: [{ key: 'main', label: 'Main', components: [component] }] }).sections[0]?.components?.[0]?.key).toBe('x');
});
