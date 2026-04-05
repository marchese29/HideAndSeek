import { memo, useEffect, useRef, useState } from 'react';
import { Animated, StyleSheet } from 'react-native';

import { useGameplayStore } from '@/stores/gameplayStore';
import type { GamePlayer, HiderActiveQuestion } from '@/types/gameplay';

import { HiderBanner } from './HiderBanner';
import { SeekerBanner } from './SeekerBanner';

interface QuestionBannerProps {
  role: 'hider' | 'seeker';
  gameId: string;
  connected: boolean;
}

export const QuestionBanner = memo(function QuestionBanner({
  role,
  gameId,
  connected,
}: QuestionBannerProps) {
  const activeQuestion = useGameplayStore((s) =>
    s.status === 'connected' ? s.state.active_question : null,
  );
  const previewQuestion = useGameplayStore((s) => s.previewQuestion);
  const seekers = useGameplayStore((s) =>
    s.status === 'connected' ? s.state.seekers : EMPTY_PLAYERS,
  );

  const visible = activeQuestion !== null || previewQuestion !== null;

  const slideAnim = useRef(new Animated.Value(0)).current;
  const [shouldRender, setShouldRender] = useState(visible);

  useEffect(() => {
    if (visible) {
      setShouldRender(true);
      Animated.timing(slideAnim, {
        toValue: 1,
        duration: 250,
        useNativeDriver: true,
      }).start();
    } else {
      Animated.timing(slideAnim, {
        toValue: 0,
        duration: 200,
        useNativeDriver: true,
      }).start(({ finished }) => {
        if (finished) setShouldRender(false);
      });
    }
  }, [visible, slideAnim]);

  if (!shouldRender) return null;

  // Render role-specific banner content
  let bannerContent = null;
  if (role === 'hider' && activeQuestion) {
    bannerContent = (
      <HiderBanner
        activeQuestion={activeQuestion as HiderActiveQuestion}
        disabled={!connected}
        gameId={gameId}
        seekers={seekers}
      />
    );
  } else if (role === 'seeker') {
    bannerContent = (
      <SeekerBanner
        activeQuestion={activeQuestion}
        previewQuestion={previewQuestion}
        disabled={!connected}
        gameId={gameId}
      />
    );
  }

  const translateY = slideAnim.interpolate({
    inputRange: [0, 1],
    outputRange: [60, 0],
  });

  return (
    <Animated.View style={[styles.wrapper, { transform: [{ translateY }], opacity: slideAnim }]}>
      {bannerContent}
    </Animated.View>
  );
});

const EMPTY_PLAYERS: GamePlayer[] = [];

const styles = StyleSheet.create({
  wrapper: {
    position: 'absolute',
    bottom: '100%',
    left: 0,
    right: 0,
    backgroundColor: '#2C3E50',
  },
});
