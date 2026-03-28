import { useAppStore } from '@/store';

/** Returns the x-client-id header object for typed API calls. */
export function authHeader() {
  return { 'x-client-id': useAppStore.getState().clientId };
}
