import { Modal, StyleSheet, Text, View } from 'react-native';

import { useCountdownTimer } from '@/hooks/useCountdownTimer';
import { usePaused } from '@/hooks/usePaused';
import { useGameplayStore } from '@/stores/gameplayStore';

function formatRemaining(seconds: number): string {
  const mm = Math.floor(seconds / 60);
  const ss = (seconds % 60).toString().padStart(2, '0');
  return `${mm}:${ss}`;
}

/**
 * Auto-presented to the claiming seeker after a successful POST /found.
 * Non-dismissable — seeker must wait for hider confirm/reject or the 2-minute server auto-dismiss.
 */
export function SeekerFoundClaimWaitingModal() {
  const pending = useGameplayStore((s) => s.foundClaimPending);
  const role = useGameplayStore((s) => s.role);
  const { paused, pausedAt } = usePaused();
  const remaining = useCountdownTimer(pending?.deadlineUtc ?? null, { paused, pausedAt });

  const visible = pending !== null && role === 'seeker';

  return (
    <Modal
      visible={visible}
      animationType="slide"
      presentationStyle="pageSheet"
      onRequestClose={() => {
        // Intentional no-op — SSE drives dismissal.
      }}
    >
      <View style={styles.container}>
        <View style={styles.body}>
          <Text style={styles.title}>Awaiting Confirmation...</Text>
          <Text style={styles.subtitle}>Waiting for hiders to confirm they were found.</Text>
          {remaining !== null && remaining > 0 && (
            <Text style={styles.countdown}>{formatRemaining(remaining)}</Text>
          )}
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#1C1C1E',
    justifyContent: 'center',
  },
  body: {
    padding: 24,
    alignItems: 'center',
  },
  title: {
    fontSize: 28,
    fontWeight: '700',
    color: '#fff',
    marginBottom: 16,
    textAlign: 'center',
  },
  subtitle: {
    fontSize: 15,
    color: 'rgba(255,255,255,0.65)',
    lineHeight: 21,
    textAlign: 'center',
    marginBottom: 32,
  },
  countdown: {
    fontSize: 56,
    fontWeight: '300',
    color: '#fff',
    fontVariant: ['tabular-nums'],
  },
});
