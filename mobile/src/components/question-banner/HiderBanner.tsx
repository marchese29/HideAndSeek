import { MaterialCommunityIcons } from '@expo/vector-icons';
import { memo, useCallback, useMemo, useState } from 'react';
import { Alert, Pressable, StyleSheet, Text, View } from 'react-native';

import { answerQuestion, vetoQuestion } from '@/api/questions';
import { useCountdownTimer } from '@/hooks/useCountdownTimer';
import { useGameInfo } from '@/hooks/useGameInfo';
import type { HiderActiveQuestion } from '@/types/gameplay';

import { BannerCountdown } from './BannerCountdown';

/** Well-known computed_answer values → human-readable labels. */
const ANSWER_LABELS: Record<string, string> = {
  yes: 'Yes',
  no: 'No',
  closer: 'Closer',
  farther: 'Farther',
  miss: 'Miss',
};

/**
 * Format a raw computed_answer value for display.
 * Well-known values get a static label; tentacle POI stable_ids are resolved
 * via the features lookup map (falls back to title-cased slug).
 */
function formatAnswerLabel(answer: string, featureNames: Map<string, string>): string {
  if (answer in ANSWER_LABELS) return ANSWER_LABELS[answer];
  const name = featureNames.get(answer);
  if (name) return name;
  // Fallback: title-case the slug (e.g. "swedish-ballard" → "Swedish Ballard")
  return answer
    .split('-')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ');
}

interface HiderBannerProps {
  activeQuestion: HiderActiveQuestion;
  computedAnswer: string | null;
  disabled: boolean;
  gameId: string;
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
  tentacles: 'asterisk',
};

function questionTypeIcon(questionType: string): keyof typeof MaterialCommunityIcons.glyphMap {
  return QUESTION_TYPE_ICONS[questionType] ?? 'help-circle-outline';
}

export const HiderBanner = memo(function HiderBanner({
  activeQuestion,
  computedAnswer,
  disabled,
  gameId,
}: HiderBannerProps) {
  const [actionInProgress, setActionInProgress] = useState(false);
  const isDisabled = disabled || actionInProgress;

  const { gameInfo } = useGameInfo(gameId);

  const remaining = useCountdownTimer(activeQuestion.question_deadline);

  // Build stable_id → name lookup for tentacle POI answers
  const featureNames = useMemo(() => {
    const map = new Map<string, string>();
    if (gameInfo?.features) {
      for (const f of gameInfo.features) {
        map.set(f.stable_id, f.name);
      }
    }
    return map;
  }, [gameInfo?.features]);

  // Resolve computed answer to a display label (null or 'null' → no answer yet)
  const answerLabel = useMemo(() => {
    if (!computedAnswer || computedAnswer === 'null') return null;
    return formatAnswerLabel(computedAnswer, featureNames);
  }, [computedAnswer, featureNames]);

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
          Waiting for lock-in{answerLabel ? ` (${answerLabel})` : ''}
        </Text>
      </View>
    );
  }

  // Answerable: urgency-colored background with action buttons
  const bgColor = urgencyColor(remaining);
  const answerDisabled = isDisabled || !answerLabel;

  return (
    <View style={[styles.container, { backgroundColor: bgColor }]}>
      <MaterialCommunityIcons
        name={questionTypeIcon(activeQuestion.question_type)}
        size={20}
        color="#fff"
      />
      <BannerCountdown deadlineIso={activeQuestion.question_deadline} />
      <Pressable
        style={({ pressed }) => [
          styles.button,
          styles.answerButton,
          answerDisabled && styles.disabled,
          pressed && !answerDisabled && styles.answerPressed,
        ]}
        disabled={answerDisabled}
        onPress={onAnswer}
      >
        <Text style={styles.buttonText} numberOfLines={1}>
          {answerLabel ?? 'Answer'}
        </Text>
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
    flexShrink: 1,
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
    flex: 1,
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
    textAlign: 'center',
  },
  disabled: {
    opacity: 0.5,
  },
});
