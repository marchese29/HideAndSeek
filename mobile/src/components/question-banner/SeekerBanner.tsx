import { MaterialCommunityIcons } from '@expo/vector-icons';
import { memo, useCallback, useMemo, useState } from 'react';
import { Alert, Pressable, StyleSheet, Text, View } from 'react-native';

import { abandonQuestion, lockInThermometer } from '@/api/questions';
import { useGameplayStore } from '@/stores/gameplayStore';
import type {
  HiderActiveQuestion,
  InventorySlotResponse,
  PreviewQuestion,
  SeekerActiveQuestion,
} from '@/types/gameplay';

import { BannerCountdown } from './BannerCountdown';

interface SeekerBannerProps {
  activeQuestion: SeekerActiveQuestion | HiderActiveQuestion | null;
  previewQuestion: PreviewQuestion | null;
  disabled: boolean;
  gameId: string;
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

function formatQuestionLabel(
  questionType: string,
  slot: InventorySlotResponse | undefined,
  convention: string,
): string {
  const typeName = questionType.charAt(0).toUpperCase() + questionType.slice(1);
  if (!slot) return typeName;
  const unit = convention === 'metric' ? 'km' : 'mi';
  if (slot.distance !== null) return `${slot.distance} ${unit}`;
  if (slot.category) return slot.category.replaceAll('_', ' ');
  return typeName;
}

export const SeekerBanner = memo(function SeekerBanner({
  activeQuestion,
  previewQuestion,
  disabled,
  gameId,
}: SeekerBannerProps) {
  const [actionInProgress, setActionInProgress] = useState(false);
  const isDisabled = disabled || actionInProgress;

  const inventory = useGameplayStore((s) =>
    s.status === 'connected' && s.role === 'seeker' ? s.state.inventory : EMPTY_INVENTORY,
  );
  const convention = useGameplayStore((s) =>
    s.status === 'connected' ? s.state.distance_convention : 'imperial',
  );

  const activeSlot = useMemo(() => {
    if (!activeQuestion) return undefined;
    return inventory.find(
      (slot) =>
        slot.question_type === activeQuestion.question_type &&
        slot.slot_index === activeQuestion.slot_index,
    );
  }, [activeQuestion, inventory]);

  const onAbandon = useCallback(() => {
    if (!activeQuestion) return;
    Alert.alert('Abandon Question', 'Abandon this question? The ask is consumed.', [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Abandon',
        style: 'destructive',
        onPress: () => {
          setActionInProgress(true);
          void abandonQuestion(gameId, activeQuestion.question_id).finally(() =>
            setActionInProgress(false),
          );
        },
      },
    ]);
  }, [activeQuestion, gameId]);

  const onLockIn = useCallback(() => {
    if (!activeQuestion) return;
    Alert.alert('Lock In', 'Lock in your current position?', [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Lock In',
        onPress: () => {
          setActionInProgress(true);
          void lockInThermometer(gameId, activeQuestion.question_id).finally(() =>
            setActionInProgress(false),
          );
        },
      },
    ]);
  }, [activeQuestion, gameId]);

  // Preview state (pre-ask) — triggered by question selection UI (dhe)
  if (previewQuestion && !activeQuestion) {
    return (
      <View style={styles.container}>
        <MaterialCommunityIcons
          name={questionTypeIcon(previewQuestion.question_type)}
          size={20}
          color="#fff"
        />
        <Text style={styles.label} numberOfLines={1}>
          {previewQuestion.question_type}
        </Text>
        <Pressable
          style={({ pressed }) => [
            styles.button,
            styles.primaryButton,
            isDisabled && styles.disabled,
            pressed && !isDisabled && styles.primaryPressed,
          ]}
          disabled={isDisabled}
          onPress={() => {
            /* Wired by dhe */
          }}
        >
          <Text style={styles.buttonText}>Ask</Text>
        </Pressable>
      </View>
    );
  }

  if (!activeQuestion) return null;

  const isThermometerInProgress =
    activeQuestion.question_type === 'thermometer' && activeQuestion.status === 'in_progress';

  // TODO: Lock-in requires min_travel distance — not yet computed client-side (wired by dhe).
  // Temporarily enabled for testing; server validates on POST.
  const lockInEnabled = true;

  // Thermometer in-progress: seeker needs to travel then lock in
  if (isThermometerInProgress) {
    return (
      <View style={styles.container}>
        <MaterialCommunityIcons name="thermometer" size={20} color="#fff" />
        <Text style={styles.label} numberOfLines={1}>
          {formatQuestionLabel('thermometer', activeSlot, convention)}
          {lockInEnabled ? ' — ready to lock in' : ' — travel to lock in'}
        </Text>
        <Pressable
          style={({ pressed }) => [
            styles.iconButton,
            styles.primaryButton,
            (isDisabled || !lockInEnabled) && styles.disabled,
            pressed && !isDisabled && lockInEnabled && styles.primaryPressed,
          ]}
          disabled={isDisabled || !lockInEnabled}
          onPress={onLockIn}
        >
          <MaterialCommunityIcons name="map-marker-check" size={20} color="#fff" />
        </Pressable>
        <Pressable
          style={({ pressed }) => [
            styles.iconButton,
            styles.destructiveButton,
            isDisabled && styles.disabled,
            pressed && !isDisabled && styles.destructivePressed,
          ]}
          disabled={isDisabled}
          onPress={onAbandon}
        >
          <MaterialCommunityIcons name="close" size={20} color="#F1C40F" />
        </Pressable>
      </View>
    );
  }

  // Active question (asked or answerable): waiting for hider to answer
  return (
    <View style={styles.container}>
      <MaterialCommunityIcons
        name={questionTypeIcon(activeQuestion.question_type)}
        size={20}
        color="#fff"
      />
      <Text style={styles.label} numberOfLines={1}>
        {formatQuestionLabel(activeQuestion.question_type, activeSlot, convention)} — waiting...
      </Text>
      <BannerCountdown deadlineIso={activeQuestion.question_deadline} />
      <Pressable
        style={({ pressed }) => [
          styles.iconButton,
          styles.destructiveButton,
          isDisabled && styles.disabled,
          pressed && !isDisabled && styles.destructivePressed,
        ]}
        disabled={isDisabled}
        onPress={onAbandon}
      >
        <MaterialCommunityIcons name="close" size={18} color="#F1C40F" />
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
    minHeight: 48,
    gap: 8,
  },
  label: {
    flex: 1,
    color: '#fff',
    fontSize: 13,
    flexShrink: 1,
  },
  button: {
    flexShrink: 0,
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: 8,
    borderWidth: 1,
  },
  iconButton: {
    flexShrink: 0,
    paddingHorizontal: 10,
    paddingVertical: 8,
    borderRadius: 8,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  primaryButton: {
    backgroundColor: 'rgba(52, 152, 219, 0.3)',
    borderColor: 'rgba(52, 152, 219, 0.5)',
  },
  primaryPressed: {
    backgroundColor: 'rgba(52, 152, 219, 0.5)',
  },
  destructiveButton: {
    backgroundColor: 'rgba(241, 196, 15, 0.2)',
    borderColor: 'rgba(241, 196, 15, 0.4)',
  },
  destructivePressed: {
    backgroundColor: 'rgba(241, 196, 15, 0.35)',
  },
  buttonText: {
    color: '#fff',
    fontSize: 13,
    fontWeight: '600',
  },
  destructiveText: {
    color: '#F1C40F',
    fontSize: 13,
    fontWeight: '600',
  },
  disabled: {
    opacity: 0.5,
  },
});

const EMPTY_INVENTORY: InventorySlotResponse[] = [];
