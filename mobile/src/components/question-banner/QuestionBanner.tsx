import { memo, useEffect, useRef, useState } from 'react';
import { Animated, StyleSheet } from 'react-native';

import { getBannerColor } from '@/constants/questionColors';
import { useGameplayStore } from '@/stores/gameplayStore';
import type { HiderActiveQuestion } from '@/types/gameplay';

import { HiderBanner } from './HiderBanner';
import { SeekerBanner } from './SeekerBanner';

const BELT_DARK = '#1C1C1E';

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
  const computedAnswer = useGameplayStore((s) =>
    s.status === 'connected' && s.role === 'hider' ? s.state.computed_answer : null,
  );
  const stationElectionStatus = useGameplayStore((s) =>
    s.status === 'connected' && s.role === 'hider' ? s.state.station_election_status : null,
  );
  const previewQuestion = useGameplayStore((s) => s.previewQuestion);

  const visible = activeQuestion !== null || previewQuestion !== null;

  // Derive banner background from question type
  const questionType = activeQuestion?.question_type ?? previewQuestion?.question_type ?? null;
  const liveBgColor = questionType ? getBannerColor(questionType) : BELT_DARK;

  // Build live banner content
  let liveContent: React.ReactNode = null;
  if (role === 'hider' && activeQuestion) {
    liveContent = (
      <HiderBanner
        activeQuestion={activeQuestion as HiderActiveQuestion}
        computedAnswer={computedAnswer}
        stationElectionStatus={stationElectionStatus}
        disabled={!connected}
        gameId={gameId}
      />
    );
  } else if (role === 'seeker') {
    liveContent = (
      <SeekerBanner
        activeQuestion={activeQuestion}
        previewQuestion={previewQuestion}
        disabled={!connected}
        gameId={gameId}
      />
    );
  }

  // Snapshot the last visible content and background so they stay frozen during slide-out.
  const lastContentRef = useRef<React.ReactNode>(null);
  const lastBgColorRef = useRef(BELT_DARK);
  if (visible && liveContent !== null) {
    lastContentRef.current = liveContent;
    lastBgColorRef.current = liveBgColor;
  }

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
        if (finished) {
          setShouldRender(false);
          lastContentRef.current = null;
          lastBgColorRef.current = BELT_DARK;
        }
      });
    }
  }, [visible, slideAnim]);

  if (!shouldRender) return null;

  const translateY = slideAnim.interpolate({
    inputRange: [0, 1],
    outputRange: [60, 0],
  });

  const bgColor = visible ? liveBgColor : lastBgColorRef.current;

  return (
    <Animated.View
      style={[
        styles.wrapper,
        { backgroundColor: bgColor, transform: [{ translateY }], opacity: slideAnim },
      ]}
    >
      {visible ? liveContent : lastContentRef.current}
    </Animated.View>
  );
});

const styles = StyleSheet.create({
  wrapper: {
    position: 'absolute',
    bottom: '100%',
    left: 0,
    right: 0,
    backgroundColor: BELT_DARK,
  },
});
