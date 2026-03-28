import type { components } from '@/api/schema';

export type PlayerColor = NonNullable<components['schemas']['PlayerColor']>;

export const COLOR_HEX: Record<PlayerColor, string> = {
  red: '#E74C3C',
  blue: '#3498DB',
  green: '#2ECC71',
  orange: '#F39C12',
  purple: '#9B59B6',
  teal: '#1ABC9C',
  pink: '#E91E63',
  amber: '#FF9800',
  cyan: '#00BCD4',
  lime: '#8BC34A',
  indigo: '#3F51B5',
  coral: '#FF6F61',
};
