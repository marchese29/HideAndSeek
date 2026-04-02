import { useLocalSearchParams } from 'expo-router';
import { useEffect } from 'react';
import { ActivityIndicator, BackHandler, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { ConnectionDot } from '@/components/ConnectionDot';
import { GameMap } from '@/components/GameMap';
import { useGameplayEvents } from '@/hooks/useGameplayEvents';
import { useGameplayStore } from '@/stores/gameplayStore';

export default function GameplayScreen() {
  const { game_id } = useLocalSearchParams<{ game_id: string }>();
  const { connected } = useGameplayEvents(game_id);
  const status = useGameplayStore((s) => s.status);
  const role = useGameplayStore((s) => s.role);
  const state = useGameplayStore((s) => s.state);

  // Suppress Android hardware back button
  useEffect(() => {
    const sub = BackHandler.addEventListener('hardwareBackPress', () => true);
    return () => sub.remove();
  }, []);

  return (
    <SafeAreaView style={styles.container} edges={['bottom']}>
      {status === 'connecting' || !role || !state ? (
        <View style={styles.loading}>
          <ActivityIndicator size="large" color="#7F8C8D" />
        </View>
      ) : (
        <GameMap role={role} state={state} />
      )}

      {/* Utility belt placeholder */}
      <View style={styles.utilityBelt}>
        <ConnectionDot connected={connected} />
        <Text style={styles.utilityBeltText}>Utility Belt</Text>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#fff',
  },
  loading: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: '#ECF0F1',
  },
  utilityBelt: {
    height: 80,
    backgroundColor: '#2C3E50',
    borderTopWidth: 1,
    borderTopColor: '#1A252F',
    justifyContent: 'center',
    alignItems: 'center',
  },
  utilityBeltText: {
    fontSize: 16,
    fontWeight: '600',
    color: '#7F8C8D',
  },
});
