import { memo } from 'react';
import { StyleSheet, Text } from 'react-native';

import { useCountdownTimer } from '@/hooks/useCountdownTimer';

interface BannerCountdownProps {
  deadlineIso: string | null;
  color?: string;
}

function formatCountdown(seconds: number): string {
  const mm = String(Math.floor(seconds / 60)).padStart(2, '0');
  const ss = String(seconds % 60).padStart(2, '0');
  return `${mm}:${ss}`;
}

export const BannerCountdown = memo(function BannerCountdown({
  deadlineIso,
  color,
}: BannerCountdownProps) {
  const remaining = useCountdownTimer(deadlineIso);
  if (remaining === null) return null;

  return (
    <Text style={[styles.text, color !== undefined && { color }]}>
      {formatCountdown(remaining)}
    </Text>
  );
});

const styles = StyleSheet.create({
  text: {
    color: '#fff',
    fontSize: 16,
    fontFamily: 'Menlo',
    fontWeight: '600',
  },
});
