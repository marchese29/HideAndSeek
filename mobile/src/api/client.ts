import createClient from 'openapi-fetch';

import type { paths } from './schema';

// eslint-disable-next-line @typescript-eslint/no-unsafe-assignment
const API_BASE_URL: string = process.env.EXPO_PUBLIC_API_BASE_URL ?? 'http://localhost:8000';

export const api = createClient<paths>({ baseUrl: API_BASE_URL });
