import { useState } from 'react';
import { Alert, Modal, Pressable, StyleSheet, Text, View } from 'react-native';

import { authHeader } from '@/api/auth';
import { api } from '@/api/client';
import { useAppStore } from '@/store';
import { useGameplayStore } from '@/stores/gameplayStore';
import type { GamePlayer, RosterPlayer } from '@/types/gameplay';

function seekerName(
  seekerPlayerId: string,
  seekers: GamePlayer[] | RosterPlayer[] | undefined,
): string {
  const match = seekers?.find((p) => p.id === seekerPlayerId);
  return match?.name ?? 'A seeker';
}

/**
 * Auto-presented to the hider when a seeker posts a found claim.
 * Non-dismissable — the hider must confirm or reject (or wait for the 2-minute timeout).
 */
export function FoundClaimModal() {
  const pending = useGameplayStore((s) => s.foundClaimPending);
  const role = useGameplayStore((s) => s.role);
  const seekers = useGameplayStore((s) => (s.status === 'connected' ? s.state.seekers : undefined));
  const gameId = useAppStore((s) => s.gameId);
  const clearFoundClaim = useGameplayStore((s) => s.clearFoundClaim);
  const [submitting, setSubmitting] = useState(false);

  const visible = pending !== null && role === 'hider';

  async function handleConfirm() {
    if (!gameId || !pending || submitting) return;
    setSubmitting(true);
    const { error } = await api.POST('/games/{game_id}/found/confirm', {
      params: { path: { game_id: gameId }, header: authHeader() },
    });
    setSubmitting(false);
    if (error) {
      // 409 means someone else already resolved it — dismiss locally
      clearFoundClaim();
      Alert.alert('Already Resolved', 'The claim was already handled.');
    }
    // On success, the game_ended SSE event clears session and navigates home.
  }

  async function handleReject() {
    if (!gameId || !pending || submitting) return;
    setSubmitting(true);
    const { error } = await api.POST('/games/{game_id}/found/reject', {
      params: { path: { game_id: gameId }, header: authHeader() },
    });
    setSubmitting(false);
    if (error) {
      clearFoundClaim();
      Alert.alert('Already Resolved', 'The claim was already handled.');
      return;
    }
    clearFoundClaim();
  }

  return (
    <Modal
      visible={visible}
      animationType="slide"
      presentationStyle="pageSheet"
      onRequestClose={() => {
        // Intentional no-op — the hider must decide. Android back button cannot dismiss.
      }}
    >
      <View style={styles.container}>
        <View style={styles.body}>
          <Text style={styles.title}>A seeker found you!</Text>
          <Text style={styles.subtitle}>
            {seekerName(pending?.seekerPlayerId ?? '', seekers)} claims to have caught the hiders.
          </Text>
          <Text style={styles.helpText}>
            Confirm to end the game, or reject if they&apos;re wrong. If you do nothing, the claim
            will auto-dismiss in 2 minutes.
          </Text>
        </View>

        <View style={styles.buttons}>
          <Pressable
            style={({ pressed }) => [
              styles.button,
              styles.rejectButton,
              pressed && styles.buttonPressed,
              submitting && styles.buttonDisabled,
            ]}
            onPress={() => {
              void handleReject();
            }}
            disabled={submitting}
          >
            <Text style={styles.rejectText}>Reject</Text>
          </Pressable>
          <Pressable
            style={({ pressed }) => [
              styles.button,
              styles.confirmButton,
              pressed && styles.buttonPressed,
              submitting && styles.buttonDisabled,
            ]}
            onPress={() => {
              void handleConfirm();
            }}
            disabled={submitting}
          >
            <Text style={styles.confirmText}>Confirm</Text>
          </Pressable>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#1C1C1E',
    justifyContent: 'space-between',
  },
  body: {
    padding: 24,
    paddingTop: 40,
  },
  title: {
    fontSize: 28,
    fontWeight: '700',
    color: '#fff',
    marginBottom: 16,
  },
  subtitle: {
    fontSize: 17,
    fontWeight: '500',
    color: 'rgba(255,255,255,0.85)',
    marginBottom: 16,
  },
  helpText: {
    fontSize: 14,
    color: 'rgba(255,255,255,0.55)',
    lineHeight: 20,
  },
  buttons: {
    flexDirection: 'row',
    padding: 16,
    gap: 12,
  },
  button: {
    flex: 1,
    paddingVertical: 16,
    borderRadius: 12,
    alignItems: 'center',
  },
  rejectButton: {
    backgroundColor: 'rgba(255,255,255,0.08)',
  },
  confirmButton: {
    backgroundColor: '#E74C3C',
  },
  buttonPressed: {
    opacity: 0.75,
  },
  buttonDisabled: {
    opacity: 0.5,
  },
  rejectText: {
    fontSize: 17,
    fontWeight: '600',
    color: 'rgba(255,255,255,0.9)',
  },
  confirmText: {
    fontSize: 17,
    fontWeight: '600',
    color: '#fff',
  },
});
