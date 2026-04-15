import { Alert, Pressable, StyleSheet, Text, View } from 'react-native';

import { useAppStore } from '@/store';

import { doEndGame } from './gameActions';

interface EndGameScreenProps {
  onDismiss: () => void;
}

export function EndGameScreen({ onDismiss }: EndGameScreenProps) {
  const gameId = useAppStore((s) => s.gameId);

  function handleEndGame() {
    if (!gameId) return;
    onDismiss();
    void (async () => {
      const success = await doEndGame(gameId);
      if (!success) {
        Alert.alert('Error', 'Failed to end game.');
      }
    })();
  }

  return (
    <View style={styles.body}>
      <View style={styles.warningBox}>
        <Text style={styles.warningText}>This will end the game for all players.</Text>
      </View>

      <Pressable
        style={({ pressed }) => [styles.destructiveButton, pressed && styles.destructivePressed]}
        onPress={handleEndGame}
      >
        <Text style={styles.destructiveButtonText}>End Game</Text>
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
});
