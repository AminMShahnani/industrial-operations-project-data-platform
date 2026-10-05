import { useEffect, useRef, useState } from 'react';
import type { components } from './api-schema';

type Field = components['schemas']['Component-Output'];
type Value = components['schemas']['Value'];
type Values = Record<string, Value>;
type Row = Record<string, string | number | boolean | null | string[]>;
function asRow(values: Values): Row {
  const result: Row = {};
  for (const [key, value] of Object.entries(values)) {
    if (!Array.isArray(value)) result[key] = value;
    else if (value.every((item): item is string => typeof item === 'string')) result[key] = value;
  }
  return result;
}
export type Lookup = (key: string, email: string, cursor: string | null) => Promise<components['schemas']['LookupPage']>;
type Result = components['schemas']['RuntimeResult'];

export function editableValues(fields: Field[], values: Values, manager = false): Values {
  const result: Values = {};
  for (const field of fields) {
    if (field.kind === 'calculated' || field.kind === 'display' || field.permissions?.write === 'manager' && !manager) continue;
    const value = values[field.key] ?? null;
    result[field.key] = field.children?.length && Array.isArray(value)
      ? value.filter(item => typeof item === 'object' && item !== null).map(row => asRow(editableValues(field.children ?? [], row as Values, manager)))
      : value;
  }
  return result;
}

function LookupField({ field, fieldKey, value, change, disabled, lookup }: {
  field: Field; fieldKey: string; value: string; change: (value: string | null) => void;
  disabled: boolean; lookup?: Lookup | undefined;
}) {
  const [email, setEmail] = useState('');
  const [items, setItems] = useState<components['schemas']['LookupItem'][]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const generation = useRef(0);
  useEffect(() => () => { generation.current += 1; }, []);
  async function load(more: boolean) {
    if (!lookup) return;
    const current = ++generation.current; setBusy(true); setError('');
    try {
      const page = await lookup(fieldKey.replace(/\[\d+\]/g, ''), email, more ? cursor : null);
      if (generation.current === current) { setItems(previous => more ? [...previous, ...page.items] : page.items); setCursor(page.next_cursor ?? null); }
    } catch { if (generation.current === current) setError('Lookup could not be loaded.'); }
    finally { if (generation.current === current) setBusy(false); }
  }
  return <span>{field.kind === 'user' && <input type="email" aria-label={`${field.label} lookup email`} value={email} disabled={disabled || busy} onChange={event => setEmail(event.target.value)} />}
    <button type="button" disabled={disabled || busy || !lookup || (field.kind === 'user' && !email)} onClick={() => void load(false)}>Load {field.label} choices</button>
    <select value={value} disabled={disabled || busy} onChange={event => change(event.target.value || null)}><option value="">Choose</option>
      {value && !items.some(item => item.id === value) && <option value={value}>Selected reference</option>}{items.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
    </select>{cursor && <button type="button" disabled={disabled || busy} onClick={() => void load(true)}>Load more {field.label} choices</button>}{error && <span role="alert">{error}</span>}</span>;
}

function resultValue(values: Values | undefined, path: string): unknown {
  let value: unknown = values;
  for (const part of path.split('.')) {
    const match = /^([a-z][a-z0-9_]*)(?:\[(\d+)\])?$/.exec(part);
    if (!match || !value || typeof value !== 'object' || Array.isArray(value)) return undefined;
    value = (value as Record<string, unknown>)[match[1] ?? ''];
    if (match[2] !== undefined) {
      if (!Array.isArray(value)) return undefined;
      value = value[Number(match[2])];
    }
  }
  return value;
}
function localDatetime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '' : new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

export function RuntimeFields({ fields, values, change, result, disabled, prefix = '', upload, lookup, manager = false, download }: {
  fields: Field[]; values: Values; change: (values: Values) => void; result?: Result | undefined;
  disabled: boolean; prefix?: string; manager?: boolean;
  download?: ((identifier: string) => Promise<void>) | undefined;
  lookup?: Lookup | undefined;
  upload?: ((key: string, file: File) => Promise<void>) | undefined;
}) {
  function set(key: string, value: Value) { change({ ...values, [key]: value }); }
  return <>{fields.map(field => {
    const key = prefix + field.key;
    const writable = field.permissions?.write !== 'manager' || manager;
    const fieldDisabled = disabled || !writable;
    if (result && !result.visible_keys.includes(key)) return null;
    const value = values[field.key];
    const errors = result?.issues.filter(issue => issue.key === key) ?? [];
    const required = result ? result.required_keys.includes(key) : field.required;
    const title = field.label + (required ? ' *' : '');
    if (field.kind === 'display') return <p key={key}>{field.label} {field.presentation?.help_text}</p>;
    if (field.kind === 'calculated') return <div key={key}><span>{title}: </span><output>{String(resultValue(result?.values.fields, key) ?? value ?? '')}</output></div>;
    if (field.children?.length) {
      const rows = Array.isArray(value) ? value.filter(row => typeof row === 'object' && row !== null) as Row[] : [];
      return <fieldset key={key} disabled={fieldDisabled}><legend>{title}</legend>{rows.map((row, index) => <fieldset key={index}><legend>Row {index + 1}</legend>
        <RuntimeFields fields={field.children ?? []} values={row} prefix={`${key}[${index}].`} result={result} disabled={fieldDisabled}
          change={updated => set(field.key, rows.map((item, position) => position === index ? asRow(updated) : item))} upload={upload} lookup={lookup} manager={manager} download={download} />
        <button type="button" onClick={() => set(field.key, rows.filter((_, position) => position !== index))}>Remove row {index + 1}</button>
      </fieldset>)}<button type="button" disabled={rows.length >= (field.validation?.max_rows ?? 100)} onClick={() => set(field.key, [...rows, {}])}>Add row to {field.label}</button></fieldset>;
    }
    if (field.kind === 'radio') return <fieldset key={key} disabled={fieldDisabled}><legend>{title}</legend>{field.choices?.map(choice => <label key={choice}><input type="radio" name={key} checked={value === choice} onChange={() => set(field.key, choice)} />{choice}</label>)}{errors.map(issue => <p role="alert" key={issue.code}>{field.label}: {issue.code.replaceAll('_', ' ')}</p>)}</fieldset>;
    const text = typeof value === 'string' || typeof value === 'number' ? String(value) : '';
    return <div key={key}><label>{title}
      {field.kind === 'textarea' ? <textarea value={text} disabled={fieldDisabled} onChange={event => set(field.key, event.target.value)} />
      : field.kind === 'boolean' ? <input type="checkbox" checked={value === true} disabled={fieldDisabled} onChange={event => set(field.key, event.target.checked)} />
      : field.kind === 'signature' ? <input type="checkbox" checked={Boolean(value)} disabled={fieldDisabled} onChange={event => set(field.key, event.target.checked ? 'I acknowledge this record' : null)} />
      : field.kind === 'select' ? <select value={text} disabled={fieldDisabled} onChange={event => set(field.key, event.target.value || null)}><option value="">Choose</option>{field.choices?.map(choice => <option key={choice}>{choice}</option>)}</select>
      : field.kind === 'multi_select' ? <select multiple value={Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []} disabled={fieldDisabled} onChange={event => set(field.key, [...event.target.selectedOptions].map(option => option.value))}>{field.choices?.map(choice => <option key={choice}>{choice}</option>)}</select>
      : field.kind === 'file' || field.kind === 'image' ? <><input type="file" disabled={fieldDisabled || !upload} accept={field.kind === 'image' ? 'image/png,image/jpeg' : '.txt,.pdf,.png,.jpg,.jpeg'} onChange={event => { const file = event.target.files?.[0]; if (file && upload) void upload(key, file); }} /><span>{text ? 'Attachment uploaded' : 'No attachment'}</span>{text && download && <button type="button" disabled={disabled} onClick={() => void download(text)}>Download {field.label}</button>}</>
      : ['user', 'department', 'project', 'master_data'].includes(field.kind) ? <LookupField field={field} fieldKey={key} value={text} change={value => set(field.key, value)} disabled={fieldDisabled} lookup={lookup} />
      : <input value={field.kind === 'datetime' ? localDatetime(text) : text} disabled={fieldDisabled} placeholder={field.presentation?.placeholder}
          type={field.kind === 'date' ? 'date' : field.kind === 'datetime' ? 'datetime-local' : field.kind === 'time' ? 'time' : 'text'}
          inputMode={field.kind === 'integer' ? 'numeric' : field.kind === 'decimal' ? 'decimal' : 'text'}
          onChange={event => {
            const raw = event.target.value;
            if (field.kind === 'integer') {
              const numeric = Number(raw);
              set(field.key, raw === '' ? null : Number.isSafeInteger(numeric) && /^-?\d+$/.test(raw) ? numeric : raw);
            } else if (field.kind === 'datetime') set(field.key, raw ? new Date(raw).toISOString() : null);
            else if (field.kind === 'time') set(field.key, raw.length === 5 ? raw + ':00' : raw || null);
            else set(field.key, raw || null);
          }} />}
    </label>{field.presentation?.help_text && <p>{field.presentation.help_text}</p>}{errors.map(issue => <p role="alert" key={issue.code}>{field.label}: {issue.code.replaceAll('_', ' ')}</p>)}</div>;
  })}</>;
}
