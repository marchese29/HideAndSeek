import { useState } from 'react';
import { Alert, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { COLOR_HEX, type PlayerColor } from '@/constants/colors';
import { useAppStore } from '@/store';
import { useGameplayStore } from '@/stores/gameplayStore';

import { doKick } from './gameActions';

interface KickPlayerScreenProps {
  onDismiss: () => void;
}

interface KickablePlayer {
  id: string;
  name: string;
  color: PlayerColor;
  role: 'hider' | 'seeker';
  lastOfRole: boolean;
}

export function KickPlayerScreen({ onDismiss }: KickPlayerScreenProps) {
  const gameId = useAppStore((s) => s.gameId);
  const playerId = useAppStore((s) => s.playerId);
  const state = useGameplayStore((s) => s.state);

  const [selected, setSelected] = useState<KickablePlayer | null>(null);

  if (!state || !playerId || !gameId) return null;

  const kickablePlayers: KickablePlayer[] = [
    ...state.hiders
      .filter((p) => p.id !== playerId)
      .map((p) => ({
        id: p.id,
        name: p.name,
        color: p.color as PlayerColor,
        role: 'hider' as const,
        lastOfRole: state.hiders.filter((h) => h.id !== playerId).length === 1,
      })),
    ...state.seekers
      .filter((p) => p.id !== playerId)
      .map((p) => ({
        id: p.id,
        name: p.name,
        color: p.color as PlayerColor,
        role: 'seeker' as const,
        lastOfRole: state.seekers.filter((s) => s.id !== playerId).length === 1,
      })),
  ];

  function handleKick() {
    if (!selected || !gameId) return;
    onDismiss();
    void (async () => {
      const success = await doKick(gameId, selected.id);
      if (!success) {
        Alert.alert('Error', 'Failed to remove player.');
      }
    })();
  }

  if (selected) {
    return (
      <View style={styles.body}>
        <View style={styles.warningBox}>
          <Text style={styles.warningTitle}>Remove {selected.name}?</Text>
          {selected.lastOfRole ? (
            <Text style={styles.warningText}>
              {selected.name} is the last {selected.role}. Removing them will end the game for
              everyone.
            </Text>
          ) : (
            <Text style={styles.warningText}>This player will be removed from the game.</Text>
          )}
        </View>

        <Pressable
          style={({ pressed }) => [styles.destructiveButton, pressed && styles.destructivePressed]}
          onPress={handleKick}
        >
          <Text style={styles.destructiveButtonText}>Remove</Text>
        </Pressable>
      </View>
    );
  }

  return (
    <View style={styles.body}>
      <Text style={styles.sectionLabel}>Choose a player to remove</Text>
      <ScrollView style={styles.playerList}>
        {kickablePlayers.map((p, index) => (
          <Pressable
            key={p.id}
            style={({ pressed }) => [
              styles.playerRow,
              index === 0 && styles.rowFirst,
              index === kickablePlayers.length - 1 && styles.rowLast,
              pressed && styles.rowPressed,
            ]}
            onPress={() => setSelected(p)}
          >
            <View style={[styles.colorDot, { backgroundColor: COLOR_HEX[p.color] }]} />
            <Text style={styles.playerName}>{p.name}</Text>
            <Text style={styles.roleLabel}>{p.role}</Text>
          </Pressable>
        ))}
      </ScrollView>
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
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
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
  colorDot: {
    width: 12,
    height: 12,
    borderRadius: 6,
  },
  playerName: {
    flex: 1,
    fontSize: 16,
    color: '#fff',
  },
  roleLabel: {
    fontSize: 13,
    color: 'rgba(255, 255, 255, 0.4)',
    textTransform: 'capitalize',
  },
});
