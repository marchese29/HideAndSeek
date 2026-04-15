import { useState } from 'react';
import { Alert, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { useAppStore } from '@/store';
import { useGameplayStore } from '@/stores/gameplayStore';

import { doLeave } from './gameActions';

interface LeaveGameScreenProps {
  onDismiss: () => void;
}

export function LeaveGameScreen({ onDismiss }: LeaveGameScreenProps) {
  const gameId = useAppStore((s) => s.gameId);
  const playerId = useAppStore((s) => s.playerId);
  const role = useGameplayStore((s) => s.role);
  const state = useGameplayStore((s) => s.state);

  const [step, setStep] = useState<'confirm' | 'pick-host'>('confirm');

  if (!state || !playerId || !gameId) return null;

  const isHost = state.host_player_id === playerId;

  const otherPlayers = [
    ...state.hiders.filter((p) => p.id !== playerId),
    ...state.seekers.filter((p) => p.id !== playerId),
  ];

  const isLastOfRole =
    role === 'hider'
      ? state.hiders.filter((h) => h.id !== playerId).length === 0
      : state.seekers.filter((s) => s.id !== playerId).length === 0;

  const needsHostTransfer = isHost && otherPlayers.length > 0 && !isLastOfRole;

  function handleLeave() {
    if (needsHostTransfer) {
      setStep('pick-host');
      return;
    }
    onDismiss();
    void doLeave(gameId!, playerId!);
  }

  function handlePickHost(newHostId: string) {
    onDismiss();
    void doLeave(gameId!, playerId!, newHostId);
  }

  if (step === 'pick-host') {
    return (
      <View style={styles.body}>
        <Text style={styles.sectionLabel}>Choose a new host before leaving</Text>
        <ScrollView style={styles.playerList}>
          {otherPlayers.map((p, index) => (
            <Pressable
              key={p.id}
              style={({ pressed }) => [
                styles.playerRow,
                index === 0 && styles.rowFirst,
                index === otherPlayers.length - 1 && styles.rowLast,
                pressed && styles.rowPressed,
              ]}
              onPress={() => {
                Alert.alert('Transfer Host', `Make ${p.name} the new host and leave?`, [
                  { text: 'Cancel', style: 'cancel' },
                  { text: 'Leave', style: 'destructive', onPress: () => handlePickHost(p.id) },
                ]);
              }}
            >
              <Text style={styles.playerName}>{p.name}</Text>
            </Pressable>
          ))}
        </ScrollView>
      </View>
    );
  }

  const roleLabel = role === 'hider' ? 'hider' : 'seeker';

  return (
    <View style={styles.body}>
      <View style={styles.warningBox}>
        {isLastOfRole ? (
          <>
            <Text style={styles.warningTitle}>You are the last {roleLabel}</Text>
            <Text style={styles.warningText}>Leaving will end the game for everyone.</Text>
          </>
        ) : (
          <Text style={styles.warningText}>Your data will be deleted and you cannot rejoin.</Text>
        )}
      </View>

      <Pressable
        style={({ pressed }) => [styles.destructiveButton, pressed && styles.destructivePressed]}
        onPress={handleLeave}
      >
        <Text style={styles.destructiveButtonText}>Leave Game</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  body: {
    flex: 1,
    padding: 16,
  },
  warningBox: {
    backgroundColor: 'rgba(231, 76, 60, 0.12)',
    borderRadius: 12,
    padding: 20,
    marginBottom: 24,
  },
  warningTitle: {
    fontSize: 16,
    fontWeight: '600',
    color: '#E74C3C',
    marginBottom: 6,
  },
  warningText: {
    fontSize: 15,
    color: 'rgba(255, 255, 255, 0.7)',
    lineHeight: 22,
  },
  destructiveButton: {
    backgroundColor: '#E74C3C',
    borderRadius: 12,
    paddingVertical: 16,
    alignItems: 'center',
  },
  destructivePressed: {
    opacity: 0.8,
  },
  destructiveButtonText: {
    fontSize: 16,
    fontWeight: '600',
    color: '#fff',
  },
  sectionLabel: {
    fontSize: 14,
    fontWeight: '600',
    color: 'rgba(255, 255, 255, 0.5)',
    marginBottom: 12,
  },
  playerList: {
    flex: 1,
  },
  playerRow: {
    paddingVertical: 14,
    paddingHorizontal: 16,
    backgroundColor: 'rgba(255, 255, 255, 0.06)',
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: 'rgba(255, 255, 255, 0.12)',
  },
  rowFirst: {
    borderTopLeftRadius: 12,
    borderTopRightRadius: 12,
  },
  rowLast: {
    borderBottomLeftRadius: 12,
    borderBottomRightRadius: 12,
    borderBottomWidth: 0,
  },
  rowPressed: {
    backgroundColor: 'rgba(255, 255, 255, 0.12)',
  },
  playerName: {
    fontSize: 16,
    color: '#fff',
  },
});
