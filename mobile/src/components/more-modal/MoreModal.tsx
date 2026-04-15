import { MaterialCommunityIcons } from '@expo/vector-icons';
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Animated,
  Modal,
  Pressable,
  StyleSheet,
  Text,
  useWindowDimensions,
  View,
} from 'react-native';

import { useAppStore } from '@/store';
import { useGameplayStore } from '@/stores/gameplayStore';

import { EndGameScreen } from './EndGameScreen';
import { KickPlayerScreen } from './KickPlayerScreen';
import { LeaveGameScreen } from './LeaveGameScreen';
import { type MenuOption, MoreMenu } from './MoreMenu';
import { PlaceholderScreen } from './PlaceholderScreen';

type Screen = 'menu' | MenuOption;

const SCREEN_TITLES: Record<Screen, string> = {
  menu: 'More',
  stats: 'Stats',
  preferences: 'Preferences',
  leave: 'Leave Game',
  'end-game': 'End Game',
  kick: 'Kick Player',
};

interface MoreModalProps {
  visible: boolean;
  onClose: () => void;
}

export function MoreModal({ visible, onClose }: MoreModalProps) {
  const [activeScreen, setActiveScreen] = useState<Screen>('menu');
  const [departingScreen, setDepartingScreen] = useState<Screen | null>(null);
  const { width } = useWindowDimensions();

  const progress = useRef(new Animated.Value(1)).current;
  const directionRef = useRef<'forward' | 'back'>('forward');

  const playerId = useAppStore((s) => s.playerId);
  const state = useGameplayStore((s) => s.state);

  // Reset to menu whenever the modal opens
  const prevVisible = useRef(visible);
  useEffect(() => {
    if (visible && !prevVisible.current) {
      setActiveScreen('menu');
      setDepartingScreen(null);
      progress.setValue(1);
    }
    prevVisible.current = visible;
  }, [visible, progress]);

  const navigate = useCallback(
    (to: Screen) => {
      setActiveScreen((current) => {
        directionRef.current = to === 'menu' ? 'back' : 'forward';
        setDepartingScreen(current);
        progress.setValue(0);
        Animated.timing(progress, {
          toValue: 1,
          duration: 250,
          useNativeDriver: true,
        }).start(() => setDepartingScreen(null));
        return to;
      });
    },
    [progress],
  );

  const goToMenu = useCallback(() => navigate('menu'), [navigate]);

  const isHost = !!(state && playerId && state.host_player_id === playerId);
  const gameIsActive = !!(state && (state.phase === 'hiding' || state.phase === 'seeking'));
  const hasOtherPlayers = !!(
    state &&
    playerId &&
    [...state.hiders, ...state.seekers].some((p) => p.id !== playerId)
  );

  // Departing screen slides out: 0 → ±width
  const departingTranslateX = progress.interpolate({
    inputRange: [0, 1],
    outputRange: [0, directionRef.current === 'forward' ? -width : width],
  });

  // Arriving screen slides in: ±width → 0
  const arrivingTranslateX = progress.interpolate({
    inputRange: [0, 1],
    outputRange: [directionRef.current === 'forward' ? width : -width, 0],
  });

  return (
    <Modal
      visible={visible}
      animationType="slide"
      presentationStyle="pageSheet"
      onRequestClose={onClose}
    >
      <View style={styles.container}>
        {/* Header */}
        <View style={styles.header}>
          {activeScreen !== 'menu' ? (
            <Pressable style={styles.backButton} onPress={goToMenu}>
              <MaterialCommunityIcons name="chevron-left" size={24} color="#3498DB" />
              <Text style={styles.backText}>Back</Text>
            </Pressable>
          ) : (
            <View style={styles.backButton} />
          )}

          <Text style={styles.title}>{SCREEN_TITLES[activeScreen]}</Text>

          <Pressable style={styles.closeButton} onPress={onClose}>
            <MaterialCommunityIcons name="close" size={22} color="rgba(255,255,255,0.6)" />
          </Pressable>
        </View>

        {/* Screen content */}
        <View style={styles.content}>
          {/* Departing screen (slides out, rendered underneath) */}
          {departingScreen !== null && (
            <Animated.View
              style={[styles.screenLayer, { transform: [{ translateX: departingTranslateX }] }]}
            >
              <ScreenContent
                screen={departingScreen}
                isHost={isHost}
                gameIsActive={gameIsActive}
                hasOtherPlayers={hasOtherPlayers}
                onSelect={navigate}
                onClose={onClose}
              />
            </Animated.View>
          )}

          {/* Active screen (slides in) */}
          <Animated.View
            style={[
              styles.screenLayer,
              departingScreen !== null && { transform: [{ translateX: arrivingTranslateX }] },
            ]}
          >
            <ScreenContent
              screen={activeScreen}
              isHost={isHost}
              gameIsActive={gameIsActive}
              hasOtherPlayers={hasOtherPlayers}
              onSelect={navigate}
              onClose={onClose}
            />
          </Animated.View>
        </View>
      </View>
    </Modal>
  );
}

// ── Screen content renderer ─────────────────────────────────────────────────

interface ScreenContentProps {
  screen: Screen;
  isHost: boolean;
  gameIsActive: boolean;
  hasOtherPlayers: boolean;
  onSelect: (option: MenuOption) => void;
  onClose: () => void;
}

function ScreenContent({
  screen,
  isHost,
  gameIsActive,
  hasOtherPlayers,
  onSelect,
  onClose,
}: ScreenContentProps) {
  switch (screen) {
    case 'menu':
      return (
        <MoreMenu
          isHost={isHost}
          gameIsActive={gameIsActive}
          hasOtherPlayers={hasOtherPlayers}
          onSelect={onSelect}
        />
      );
    case 'stats':
    case 'preferences':
      return <PlaceholderScreen />;
    case 'leave':
      return <LeaveGameScreen onDismiss={onClose} />;
    case 'end-game':
      return <EndGameScreen onDismiss={onClose} />;
    case 'kick':
      return <KickPlayerScreen onDismiss={onClose} />;
  }
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#1C1C1E',
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 12,
    paddingTop: 16,
    paddingBottom: 12,
  },
  backButton: {
    flexDirection: 'row',
    alignItems: 'center',
    minWidth: 70,
  },
  backText: {
    fontSize: 16,
    color: '#3498DB',
  },
  title: {
    fontSize: 18,
    fontWeight: '600',
    color: '#fff',
  },
  closeButton: {
    minWidth: 70,
    alignItems: 'flex-end',
  },
  content: {
    flex: 1,
    overflow: 'hidden',
  },
  screenLayer: {
    ...StyleSheet.absoluteFillObject,
  },
});
