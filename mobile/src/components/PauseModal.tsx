import { MaterialCommunityIcons } from '@expo/vector-icons';
import { Modal, StyleSheet, Text, View } from 'react-native';

import { usePaused } from '@/hooks/usePaused';
import type { PauseReason } from '@/types/gameplay';
import { isUniversalCategory } from '@/utils/pauseCategory';

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
 * Universal pause modal — non-dismissable, no actions in m8r.6.
 * Resume/End Game host buttons land in m8r.9; rest-period countdown lands
 * with its own future epic.
 */
export function PauseModal() {
  const { paused, pauseReasons } = usePaused();
  const visible = paused && isUniversalCategory(pauseReasons);
  const { title, body } = copyForReasons(pauseReasons);

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
    padding: 32,
    alignItems: 'center',
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
});
