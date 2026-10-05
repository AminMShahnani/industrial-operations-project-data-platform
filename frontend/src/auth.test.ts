import { describe, expect, it } from 'vitest';
import { InMemoryWebStorage } from 'oidc-client-ts';
import { authSettings } from './auth';
import { apiClient } from './client';

describe('OIDC configuration and token handling', () => {
  it('fails closed for missing/partial trust and plaintext production providers', () => {
    const storage = new InMemoryWebStorage();
    expect(authSettings(undefined, undefined, 'https://app.test/', storage, true)).toBeUndefined();
    expect(() => authSettings('https://id.test', undefined, 'https://app.test/', storage, true)).toThrow();
    expect(() => authSettings('http://id.test', 'web', 'https://app.test/', storage, true)).toThrow();
  });
  it('uses code flow and keeps tokens out of persistent browser storage', async () => {
    const storage = new InMemoryWebStorage();
    const settings = authSettings('https://id.test', 'web', 'https://app.test/', storage, true);
    expect(settings?.response_type).toBe('code');
    expect(settings?.disablePKCE).not.toBe(true);
    await settings?.userStore?.set('token', 'private-access-token');
    expect(storage.length).toBe(0);
    expect(await settings?.userStore?.get('token')).toBe('private-access-token');
  });
  it('sends bearer tokens only in headers and rejects redirects', async () => {
    let request: Request | undefined;
    const previousFetch = globalThis.fetch;
    globalThis.fetch = async input => {
      request = input as Request;
      return new Response(JSON.stringify({ issuer: 'https://id.test', subject: 'user', memberships: [] }), {
        headers: { 'Content-Type': 'application/json' },
      });
    };
    try {
      const result = await apiClient('https://api.test', 'private-access-token').GET('/api/v1/me');
      expect(result.data?.subject).toBe('user');
      expect(request?.headers.get('Authorization')).toBe('Bearer private-access-token');
      expect(request?.url).not.toContain('private-access-token');
      expect(request?.credentials).toBe('omit');
      expect(request?.redirect).toBe('error');
    } finally { globalThis.fetch = previousFetch; }
  });
});
