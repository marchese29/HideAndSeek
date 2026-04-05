import { MaterialCommunityIcons } from '@expo/vector-icons';
import { memo, useCallback, useMemo, useState } from 'react';
import { Alert, Pressable, StyleSheet, Text, View } from 'react-native';

import { answerQuestion, vetoQuestion } from '@/api/questions';
import { useCountdownTimer } from '@/hooks/useCountdownTimer';
import type { GamePlayer, HiderActiveQuestion } from '@/types/gameplay';

import { BannerCountdown } from './BannerCountdown';

interface HiderBannerProps {
  activeQuestion: HiderActiveQuestion;
  disabled: boolean;
  gameId: string;
  seekers: GamePlayer[];
}

const URGENCY_GREEN = '#2ECC71';
const URGENCY_YELLOW = '#F1C40F';
const URGENCY_RED = '#E74C3C';
const WAITING_GRAY = '#7F8C8D';

function urgencyColor(remainingSeconds: number | null): string {
  if (remainingSeconds === null) return WAITING_GRAY;
  if (remainingSeconds > 120) return URGENCY_GREEN;
  if (remainingSeconds > 60) return URGENCY_YELLOW;
  return URGENCY_RED;
}

const QUESTION_TYPE_ICONS: Record<string, keyof typeof MaterialCommunityIcons.glyphMap> = {
  radar: 'radar',
  thermometer: 'thermometer',
  matching: 'map-marker-multiple',
  measuring: 'ruler',
};

function questionTypeIcon(questionType: string): keyof typeof MaterialCommunityIcons.glyphMap {
  return QUESTION_TYPE_ICONS[questionType] ?? 'help-circle-outline';
}

export const HiderBanner = memo(function HiderBanner({
  activeQuestion,
  disabled,
  gameId,
  seekers,
}: HiderBannerProps) {
  const [actionInProgress, setActionInProgress] = useState(false);
  const isDisabled = disabled || actionInProgress;

  const seekerName = useMemo(() => {
    const seeker = seekers.find((s) => s.id === activeQuestion.asked_by);
    return seeker?.name ?? 'Seeker';
  }, [seekers, activeQuestion.asked_by]);

  const remaining = useCountdownTimer(activeQuestion.question_deadline);

  const onAnswer = useCallback(() => {
    Alert.alert('Answer Question', 'Answer from your current location?', [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Answer',
        onPress: () => {
          setActionInProgress(true);
          void answerQuestion(gameId, activeQuestion.question_id).finally(() =>
            setActionInProgress(false),
          );
        },
      },
    ]);
  }, [gameId, activeQuestion.question_id]);

  const onPowerUp = useCallback(() => {
    Alert.alert('Power-Up', 'Choose a power-up:', [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Veto',
        onPress: () => {
          Alert.alert('Veto', 'Veto this question? No exclusion zone will be produced.', [
            { text: 'Cancel', style: 'cancel' },
            {
              text: 'Veto',
              onPress: () => {
                setActionInProgress(true);
                void vetoQuestion(gameId, activeQuestion.question_id).finally(() =>
                  setActionInProgress(false),
                );
              },
            },
          ]);
        },
      },
      {
        text: 'Randomize (coming soon)',
        isPreferred: false,
        onPress: () => {
          Alert.alert('Coming Soon', 'Randomize power-up is not yet available.');
        },
      },
    ]);
  }, [gameId, activeQuestion.question_id]);

  const isThermometerPreLockIn =
    activeQuestion.question_type === 'thermometer' &&
    (activeQuestion.status === 'asked' || activeQuestion.status === 'in_progress');

  // Thermometer pre-lock-in: gray background, no actions
  if (isThermometerPreLockIn) {
    return (
      <View style={[styles.container, { backgroundColor: WAITING_GRAY }]}>
        <MaterialCommunityIcons name="thermometer" size={20} color="#fff" />
        <Text style={styles.label} numberOfLines={1}>
          Thermometer from {seekerName} — waiting for lock-in
        </Text>
      </View>
    );
  }

  // Answerable: urgency-colored background with action buttons
  const bgColor = urgencyColor(remaining);

  return (
    <View style={[styles.container, { backgroundColor: bgColor }]}>
      <MaterialCommunityIcons
        name={questionTypeIcon(activeQuestion.question_type)}
        size={20}
        color="#fff"
      />
      <Text style={styles.label} numberOfLines={1}>
        {activeQuestion.question_type} from {seekerName}
      </Text>
      <BannerCountdown deadlineIso={activeQuestion.question_deadline} />
      <Pressable
        style={({ pressed }) => [
          styles.button,
          styles.answerButton,
          isDisabled && styles.disabled,
          pressed && !isDisabled && styles.answerPressed,
        ]}
        disabled={isDisabled}
        onPress={onAnswer}
      >
        <Text style={styles.buttonText}>Answer</Text>
      </Pressable>
      <Pressable
        style={({ pressed }) => [
          styles.button,
          styles.powerUpButton,
          isDisabled && styles.disabled,
          pressed && !isDisabled && styles.powerUpPressed,
        ]}
        disabled={isDisabled}
        onPress={onPowerUp}
      >
        <MaterialCommunityIcons name="lightning-bolt" size={16} color="#fff" />
      </Pressable>
    </View>
  );
});

const styles = StyleSheet.create({
  container: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 12,
    paddingVertical: 10,
    gap: 8,
  },
  label: {
    flex: 1,
    color: '#fff',
    fontSize: 14,
  },
  button: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 8,
    borderWidth: 1,
  },
  answerButton: {
    backgroundColor: 'rgba(255, 255, 255, 0.2)',
    borderColor: 'rgba(255, 255, 255, 0.4)',
  },
  answerPressed: {
    backgroundColor: 'rgba(255, 255, 255, 0.35)',
  },
  powerUpButton: {
    backgroundColor: 'rgba(255, 255, 255, 0.15)',
    borderColor: 'rgba(255, 255, 255, 0.3)',
    paddingHorizontal: 8,
  },
  powerUpPressed: {
    backgroundColor: 'rgba(255, 255, 255, 0.3)',
  },
  buttonText: {
    color: '#fff',
    fontSize: 13,
    fontWeight: '600',
  },
  disabled: {
    opacity: 0.5,
  },
});
