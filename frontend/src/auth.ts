import { InMemoryWebStorage, WebStorageStateStore, type UserManagerSettings } from 'oidc-client-ts';

export function authSettings(
  authority: string | undefined, clientId: string | undefined, redirectUri: string,
  stateStorage: Storage, production: boolean,
): UserManagerSettings | undefined {
  if (!authority && !clientId) return undefined;
  if (!authority || !clientId) throw new Error('Identity configuration is incomplete');
  const issuer = new URL(authority);
  if (issuer.protocol !== 'https:' &&
      (production || !['localhost', '127.0.0.1'].includes(issuer.hostname))) {
    throw new Error('Identity configuration requires HTTPS');
  }
  return {
    authority, client_id: clientId, redirect_uri: redirectUri,
    post_logout_redirect_uri: redirectUri, response_type: 'code', scope: 'openid email profile',
    automaticSilentRenew: false, loadUserInfo: false,
    userStore: new WebStorageStateStore({ store: new InMemoryWebStorage() }),
    stateStore: new WebStorageStateStore({ store: stateStorage }),
  };
}
