import { MaterialCommunityIcons } from '@expo/vector-icons';
import { useEffect, useState } from 'react';
import { Alert, Modal, Pressable, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { authHeader } from '@/api/auth';
import { api } from '@/api/client';
import { getTypeColors } from '@/constants/questionColors';
import { useGameplayStore } from '@/stores/gameplayStore';
import type { InventorySlotResponse } from '@/types/gameplay';
import { type PhotoSubject, photoSubjectLabel } from '@/utils/photoSubjects';

import { DistanceFamily } from './DistanceFamily';
import { PhotoFamily } from './PhotoFamily';

type QuestionType = 'radar' | 'thermometer' | 'matching' | 'measuring' | 'tentacles' | 'photo';

export type PickerSelection =
  | { kind: 'photo'; subject: PhotoSubject | null }
  | {
      kind: 'distance';
      slot: InventorySlotResponse | null;
      customValue: number | null;
    };

interface QuestionPickerModalProps {
  visible: boolean;
  questionType: QuestionType;
  gameId: string;
  inventory: InventorySlotResponse[];
  selection: PickerSelection;
  onSelectionChange: (selection: PickerSelection) => void;
  onClose: () => void;
}

const TYPE_LABELS: Partial<Record<QuestionType, string>> = {
  photo: 'Photo',
  radar: 'Radar',
  thermometer: 'Thermometer',
  matching: 'Matching',
  measuring: 'Measuring',
  tentacles: 'Tentacles',
};

const ASK_PATHS = {
  radar: '/games/{game_id}/questions/radar',
  thermometer: '/games/{game_id}/questions/thermometer',
} as const;

export function QuestionPickerModal({
  visible,
  questionType,
  gameId,
  inventory,
  selection,
  onSelectionChange,
  onClose,
}: QuestionPickerModalProps) {
  const insets = useSafeAreaInsets();
  const colors = getTypeColors(questionType);

  const hasActiveQuestion = useGameplayStore(
    (s) =>
      s.status === 'connected' &&
      s.role === 'seeker' &&
      s.state.phase === 'seeking' &&
      s.state.active_question != null,
  );
  const connectionStatus = useGameplayStore((s) => s.status);

  const [submitting, setSubmitting] = useState(false);
  const [hasInteracted, setHasInteracted] = useState(false);

  useEffect(() => {
    if (visible) setHasInteracted(false);
  }, [visible]);

  const markInteracted = () => setHasInteracted(true);

  const selectionReady =
    selection.kind === 'photo' ? selection.subject != null : selection.slot != null;

  const submitEnabled =
    !submitting && selectionReady && !hasActiveQuestion && connectionStatus === 'connected';

  const performSubmit = () => {
    const location = useGameplayStore.getState().selfLocation?.coordinates;
    if (!location) {
      Alert.alert('Location Unavailable', 'Cannot determine your position. Try again.');
      return;
    }

    if (selection.kind === 'photo') {
      if (!selection.subject) return;
      const slot = inventory.find(
        (s) => s.question_type === 'photo' && s.photo_subject === selection.subject,
      );
      if (!slot) {
        Alert.alert('Error', 'Selected photo subject is no longer available.');
        return;
      }
      setSubmitting(true);
      void api
        .POST('/games/{game_id}/questions/photo', {
          params: { path: { game_id: gameId }, header: authHeader() },
          body: { slot_index: slot.slot_index, location },
        })
        .then(({ error }) => {
          if (error) {
            const detail = (error as { detail?: string }).detail;
            Alert.alert('Error', detail ?? 'Failed to ask question.');
          } else {
            onClose();
          }
        })
        .finally(() => setSubmitting(false));
      return;
    }

    // distance: radar | thermometer
    if (!selection.slot) return;
    if (questionType !== 'radar' && questionType !== 'thermometer') return;
    const path = ASK_PATHS[questionType];
    setSubmitting(true);
    void api
      .POST(path, {
        params: { path: { game_id: gameId }, header: authHeader() },
        body: {
          slot_index: selection.slot.slot_index,
          location,
          custom_distance: selection.customValue,
        },
      })
      .then(({ error }) => {
        if (error) {
          const detail = (error as { detail?: string }).detail;
          Alert.alert('Error', detail ?? 'Failed to ask question.');
        } else {
          onClose();
        }
      })
      .finally(() => setSubmitting(false));
  };

  const onSubmitPress = () => {
    if (!submitEnabled) return;
    if (!hasInteracted) {
      const promptText = buildConfirmText(questionType, selection);
      Alert.alert('Confirm', promptText, [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Confirm', onPress: performSubmit },
      ]);
      return;
    }
    performSubmit();
  };

  return (
    <Modal
      visible={visible}
      animationType="slide"
      presentationStyle="pageSheet"
      onRequestClose={onClose}
    >
      <View style={styles.container}>
        <View style={[styles.header, { backgroundColor: colors.active }]}>
          <Text style={[styles.title, { color: colors.onActive }]}>
            {TYPE_LABELS[questionType] ?? questionType}
          </Text>
          <Pressable style={styles.closeButton} onPress={onClose}>
            <MaterialCommunityIcons name="close" size={22} color={colors.onActive} />
          </Pressable>
        </View>

        <View style={styles.body}>
          {questionType === 'photo' && selection.kind === 'photo' && (
            <PhotoFamily
              slots={inventory}
              selectedSubject={selection.subject}
              onSelectSubject={(subject) => {
                markInteracted();
                onSelectionChange({ kind: 'photo', subject });
              }}
            />
          )}
          {(questionType === 'radar' || questionType === 'thermometer') &&
            selection.kind === 'distance' && (
              <DistanceFamily
                questionType={questionType}
                gameId={gameId}
                slots={inventory}
                selectedSlot={selection.slot}
                customValue={selection.customValue}
                onSelect={(slot, customValue) =>
                  onSelectionChange({ kind: 'distance', slot, customValue })
                }
                onInteract={markInteracted}
              />
            )}
        </View>

        <View style={[styles.footer, { paddingBottom: insets.bottom + 12 }]}>
          {hasActiveQuestion && (
            <Text style={styles.waitingHint}>Waiting on an Active Question</Text>
          )}
          <Pressable
            style={[
              styles.submitButton,
              { backgroundColor: submitEnabled ? colors.active : '#3A3A3C' },
            ]}
            onPress={onSubmitPress}
            disabled={!submitEnabled}
          >
            <Text
              style={[
                styles.submitText,
                { color: submitEnabled ? colors.onActive : 'rgba(255,255,255,0.4)' },
              ]}
            >
              {submitting ? 'Submitting…' : 'Submit'}
            </Text>
          </Pressable>
        </View>
      </View>
    </Modal>
  );
}

function buildConfirmText(questionType: QuestionType, selection: PickerSelection): string {
  if (selection.kind === 'photo' && selection.subject) {
    const label = photoSubjectLabel(selection.subject);
    const phrased = label.charAt(0).toLowerCase() + label.slice(1);
    return `Ask for a photo of ${phrased}?`;
  }
  const typeLabel = TYPE_LABELS[questionType] ?? questionType;
  return `Ask ${typeLabel}?`;
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
    paddingHorizontal: 16,
    paddingTop: 16,
    paddingBottom: 12,
  },
  title: {
    fontSize: 18,
    fontWeight: '600',
  },
  closeButton: {
    padding: 4,
  },
  body: {
    flex: 1,
  },
  footer: {
    paddingHorizontal: 16,
    paddingTop: 12,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: 'rgba(255,255,255,0.1)',
  },
  waitingHint: {
    fontSize: 12,
    color: 'rgba(255,255,255,0.5)',
    marginBottom: 6,
    textAlign: 'center',
  },
  submitButton: {
    paddingVertical: 14,
    borderRadius: 12,
    alignItems: 'center',
  },
  submitText: {
    fontSize: 16,
    fontWeight: '600',
  },
});
