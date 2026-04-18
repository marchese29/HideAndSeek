import { router, useLocalSearchParams } from 'expo-router';
import { useEffect } from 'react';
import { BackHandler, Pressable, StyleSheet, Text, View } from 'react-native';

import { useAppStore } from '@/store';

type RecapReason =
  | 'found'
  | 'host_ended'
  | 'last_player'
  | 'no_hiders_remaining'
  | 'no_seekers_remaining';

type Role = 'hider' | 'seeker';

function recapCopy(reason: string, role: string): string {
  switch (reason as RecapReason) {
    case 'found':
      return role === 'hider' ? 'The seekers found you!' : 'You found the hiders!';
    case 'host_ended':
      return 'The host ended the game';
    case 'last_player':
      return 'All players left';
    case 'no_hiders_remaining':
      return 'No hiders remaining';
    case 'no_seekers_remaining':
      return 'No seekers remaining';
    default:
      return 'The game has ended';
  }
}

export default function RecapScreen() {
  const { reason, role } = useLocalSearchParams<{ reason: string; role: Role }>();

  useEffect(() => {
    const sub = BackHandler.addEventListener('hardwareBackPress', () => true);
    return () => sub.remove();
  }, []);

  function goHome() {
    useAppStore.getState().clearSession();
    router.replace('/');
  }

  return (
    <View style={styles.container}>
      <View style={styles.content}>
        <Text style={styles.title}>Game Over</Text>
        <Text style={styles.subtitle}>{recapCopy(reason ?? '', role ?? '')}</Text>
      </View>
      <View style={styles.buttons}>
        <Pressable style={styles.button} onPress={goHome}>
          <Text style={styles.buttonText}>Home</Text>
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: 24,
    backgroundColor: '#fff',
  },
  content: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  title: {
    fontSize: 32,
    fontWeight: 'bold',
    marginBottom: 16,
  },
  subtitle: {
    fontSize: 17,
    color: 'rgba(0,0,0,0.6)',
    textAlign: 'center',
  },
  buttons: {
    width: '100%',
    gap: 16,
    paddingBottom: 24,
  },
  button: {
    backgroundColor: '#3498DB',
    paddingVertical: 16,
    borderRadius: 12,
    alignItems: 'center',
  },
  buttonText: {
    color: '#fff',
    fontSize: 18,
    fontWeight: '600',
  },
});
