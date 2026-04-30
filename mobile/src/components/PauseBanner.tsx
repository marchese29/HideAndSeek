import { MaterialCommunityIcons } from '@expo/vector-icons';
import { StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { usePaused } from '@/hooks/usePaused';
import { useGameplayStore } from '@/stores/gameplayStore';
import type { PauseReason } from '@/types/gameplay';
import { isUniversalCategory } from '@/utils/pauseCategory';

/**
 * Resolves the queued/uploaded hider's display name from the active question
 * snapshot. Returns null when the active question is not a queued/submitted
 * hider photo or the player can't be looked up.
 */
function useQueuedHiderName(): string | null {
  return useGameplayStore((s) => {
    if (s.status !== 'connected' || s.role !== 'hider') return null;
    const active = s.state.active_question;
    if (!active) return null;
    // photo_queued_by lives only on the hider snapshot's active_question.
    const queuedBy = (active as { photo_queued_by?: string | null }).photo_queued_by;
    if (!queuedBy) return null;
    return s.state.hiders.find((p) => p.id === queuedBy)?.name ?? null;
  });
}

function copyForReason(
  reason: PauseReason,
  role: 'hider' | 'seeker' | undefined,
  queuedHiderName: string | null,
): string {
  if (reason === 'photo_question_open') {
    if (role === 'seeker') {
      const who = queuedHiderName ?? 'a hider';
      return `Paused — waiting on ${who}'s photo.`;
    }
    return 'Paused — your photo is under review.';
  }
  // host / rest_period are universal categories — handled by PauseModal, not the banner.
  return 'Paused.';
}

export function PauseBanner() {
  const insets = useSafeAreaInsets();
  const { paused, pauseReasons } = usePaused();
  const role = useGameplayStore((s) => s.role);
  const queuedHiderName = useQueuedHiderName();

  if (!paused) return null;
  if (isUniversalCategory(pauseReasons)) return null;
  if (pauseReasons.length === 0) return null;

  // First reason wins for copy — practical reason set is small (currently photo).
  const message = copyForReason(pauseReasons[0], role, queuedHiderName);

  return (
    <View pointerEvents="box-none" style={[styles.wrapper, { top: insets.top + 8 }]}>
      <View accessibilityLiveRegion="polite" accessibilityRole="alert" style={styles.banner}>
        <MaterialCommunityIcons name="pause-circle" size={18} color="#fff" style={styles.icon} />
        <Text style={styles.text}>{message}</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrapper: {
    position: 'absolute',
    left: 0,
    right: 0,
    zIndex: 200,
    alignItems: 'center',
    paddingHorizontal: 16,
  },
  banner: {
    flexDirection: 'row',
    alignItems: 'center',
    width: '100%',
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderRadius: 10,
    backgroundColor: '#34495E',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.25,
    shadowRadius: 4,
    elevation: 4,
  },
  icon: {
    marginRight: 8,
  },
  text: {
    flex: 1,
    color: '#fff',
    fontSize: 14,
    fontWeight: '600',
    textAlign: 'center',
  },
});
