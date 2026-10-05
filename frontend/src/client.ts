import createClient from 'openapi-fetch';
import type { paths } from './api-schema';

export function apiClient(baseUrl: string, accessToken: string) {
  return createClient<paths>({
    baseUrl,
    headers: { Authorization: `Bearer ${accessToken}` },
    redirect: 'error',
    credentials: 'omit',
  });
}
