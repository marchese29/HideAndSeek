import { MaterialCommunityIcons } from '@expo/vector-icons';
import { useState } from 'react';
import { Alert, Modal, Pressable, StyleSheet, Text, View } from 'react-native';

import { usePaused } from '@/hooks/usePaused';
import { useAppStore } from '@/store';
import { useGameplayStore } from '@/stores/gameplayStore';
import type { PauseReason } from '@/types/gameplay';
import { isUniversalCategory } from '@/utils/pauseCategory';

import { doEndGame, doResume } from './more-modal/gameActions';

function copyForReasons(reasons: PauseReason[]): { title: string; body: string } {
  // Strictest category wins — host overrides rest_period when stacked.
  if (reasons.includes('host')) {
    return { title: 'Game Paused', body: 'The host has paused the game.' };
  }
  if (reasons.includes('rest_period')) {
    return { title: 'Rest Period', body: 'The game is paused for a rest period.' };
  }
  return { title: 'Game Paused', body: 'The game is paused.' };
}

/**
 * Universal pause modal — non-dismissable. Renders Resume + End Game buttons
 * for the host while `host` is in active_pause_reasons; non-host viewers see
 * only the title + body.
 */
export function PauseModal() {
  const { paused, pauseReasons } = usePaused();
  const visible = paused && isUniversalCategory(pauseReasons);
  const { title, body } = copyForReasons(pauseReasons);

  const playerId = useAppStore((s) => s.playerId);
  const gameId = useAppStore((s) => s.gameId);
  const hostPlayerId = useGameplayStore((s) =>
    s.status === 'connected' ? s.state.host_player_id : null,
  );
  const isHost = !!(playerId && hostPlayerId && hostPlayerId === playerId);
  const showHostControls = pauseReasons.includes('host') && isHost;

  const [submitting, setSubmitting] = useState(false);

  async function handleResume() {
    if (!gameId || submitting) return;
    setSubmitting(true);
    const ok = await doResume(gameId);
    setSubmitting(false);
    if (!ok) Alert.alert('Error', 'Failed to resume game.');
  }

  async function handleEndGame() {
    if (!gameId || submitting) return;
    setSubmitting(true);
    const ok = await doEndGame(gameId);
    setSubmitting(false);
    if (!ok) Alert.alert('Error', 'Failed to end game.');
  }

  return (
    <Modal
      visible={visible}
      animationType="slide"
      presentationStyle="pageSheet"
      onRequestClose={() => {
        // Intentional no-op — pause is server-driven; hardware back can't dismiss.
      }}
    >
      <View style={styles.container}>
        <View style={styles.body}>
          <MaterialCommunityIcons name="pause-circle" size={64} color="#fff" />
          <Text style={styles.title}>{title}</Text>
          <Text style={styles.subtitle}>{body}</Text>
        </View>

        {showHostControls && (
          <View style={styles.buttons}>
            <Pressable
              style={({ pressed }) => [
                styles.button,
                styles.endGameButton,
                pressed && styles.buttonPressed,
                submitting && styles.buttonDisabled,
              ]}
              onPress={() => {
                void handleEndGame();
              }}
              disabled={submitting}
            >
              <Text style={styles.endGameText}>End Game</Text>
            </Pressable>
            <Pressable
              style={({ pressed }) => [
                styles.button,
                styles.resumeButton,
                pressed && styles.buttonPressed,
                submitting && styles.buttonDisabled,
              ]}
              onPress={() => {
                void handleResume();
              }}
              disabled={submitting}
            >
              <Text style={styles.resumeText}>Resume</Text>
            </Pressable>
          </View>
        )}
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
    flex: 1,
    padding: 32,
    alignItems: 'center',
    justifyContent: 'center',
  },
  title: {
    fontSize: 28,
    fontWeight: '700',
    color: '#fff',
    marginTop: 24,
    marginBottom: 16,
    textAlign: 'center',
  },
  subtitle: {
    fontSize: 17,
    color: 'rgba(255,255,255,0.65)',
    lineHeight: 23,
    textAlign: 'center',
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
  endGameButton: {
    backgroundColor: '#E74C3C',
  },
  resumeButton: {
    backgroundColor: '#3498DB',
  },
  buttonPressed: {
    opacity: 0.75,
  },
  buttonDisabled: {
    opacity: 0.5,
  },
  endGameText: {
    fontSize: 17,
    fontWeight: '600',
    color: '#fff',
  },
  resumeText: {
    fontSize: 17,
    fontWeight: '600',
    color: '#fff',
  },
});
