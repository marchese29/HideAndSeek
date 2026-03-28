import createClient from 'openapi-fetch';
import { Platform } from 'react-native';

import { useAppStore } from '@/store';

import type { paths } from './schema';

function getDefaultBaseUrl(): string {
  if (Platform.OS === 'android') {
    return 'http://10.0.2.2:8000';
  }
  return 'http://localhost:8000';
}

// eslint-disable-next-line @typescript-eslint/no-unsafe-assignment
export const API_BASE_URL: string = process.env.EXPO_PUBLIC_API_BASE_URL ?? getDefaultBaseUrl();

export const api = createClient<paths>({ baseUrl: API_BASE_URL });

api.use({
  onRequest({ request }) {
    const { clientId } = useAppStore.getState();
    request.headers.set('x-client-id', clientId);
    return request;
  },
});
