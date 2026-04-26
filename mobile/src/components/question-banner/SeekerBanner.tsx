import { MaterialCommunityIcons } from '@expo/vector-icons';
import { memo, useCallback, useMemo, useState } from 'react';
import { Alert, Image, Pressable, StyleSheet, Text, View } from 'react-native';

import { authHeader } from '@/api/auth';
import { api, API_BASE_URL } from '@/api/client';
import { abandonQuestion, acceptPhoto, lockInThermometer, rejectPhoto } from '@/api/questions';
import { getTypeColors } from '@/constants/questionColors';
import { useGameInfo } from '@/hooks/useGameInfo';
import { usePreviewBoundary } from '@/hooks/usePreviewBoundary';
import { useGameplayStore } from '@/stores/gameplayStore';
import type {
  HiderActiveQuestion,
  InventorySlotResponse,
  PreviewQuestion,
  SeekerActiveQuestion,
  ThermometerEventParams,
} from '@/types/gameplay';
import { haversineMeters, metersToConvention } from '@/utils/geo';
import { photoSubjectLabel } from '@/utils/photoSubjects';

import { BannerCountdown } from './BannerCountdown';

/** Adaptive button styling: uses dark overlays when text is dark, white overlays otherwise. */
function buttonStyle(onActive: string) {
  const dark = onActive !== '#fff';
  return {
    backgroundColor: dark ? 'rgba(0, 0, 0, 0.1)' : 'rgba(255, 255, 255, 0.2)',
    borderColor: dark ? 'rgba(0, 0, 0, 0.2)' : 'rgba(255, 255, 255, 0.4)',
  };
}

function buttonPressedStyle(onActive: string) {
  const dark = onActive !== '#fff';
  return { backgroundColor: dark ? 'rgba(0, 0, 0, 0.2)' : 'rgba(255, 255, 255, 0.35)' };
}

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
  tentacles: 'asterisk',
  photo: 'camera',
};

function questionTypeIcon(questionType: string): keyof typeof MaterialCommunityIcons.glyphMap {
  return QUESTION_TYPE_ICONS[questionType] ?? 'help-circle-outline';
}

const ASK_PATHS = {
  radar: '/games/{game_id}/questions/radar',
  thermometer: '/games/{game_id}/questions/thermometer',
  matching: '/games/{game_id}/questions/matching',
  measuring: '/games/{game_id}/questions/measuring',
  tentacles: '/games/{game_id}/questions/tentacles',
} as const;

function formatQuestionLabel(
  questionType: string,
  slot: InventorySlotResponse | undefined,
  convention: string,
): string {
  if (questionType === 'photo' && slot?.photo_subject) {
    return photoSubjectLabel(slot.photo_subject);
  }
  const typeName = questionType.charAt(0).toUpperCase() + questionType.slice(1);
  if (!slot) return typeName;
  const unit = convention === 'metric' ? 'km' : 'mi';
  // Tentacles: both category and distance are set
  if (slot.category && slot.distance !== null) {
    const label = slot.category.replaceAll('_', ' ');
    return `${label} (${slot.distance} ${unit})`;
  }
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
  const { gameInfo } = useGameInfo(gameId);
  const convention = gameInfo?.distance_convention ?? 'imperial';
  const selfLocation = useGameplayStore((s) => s.selfLocation);
  const { tentaclePois } = usePreviewBoundary();

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

  const onAcceptPhoto = useCallback(() => {
    if (!activeQuestion) return;
    Alert.alert('Accept Photo', 'Accept this photo? The question will be answered.', [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Accept',
        onPress: () => {
          setActionInProgress(true);
          void acceptPhoto(gameId, activeQuestion.question_id).finally(() =>
            setActionInProgress(false),
          );
        },
      },
    ]);
  }, [activeQuestion, gameId]);

  const onRejectPhoto = useCallback(() => {
    if (!activeQuestion) return;
    Alert.alert('Reject Photo', 'Reject this photo? The hider will need to submit a new one.', [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Reject',
        style: 'destructive',
        onPress: () => {
          setActionInProgress(true);
          void rejectPhoto(gameId, activeQuestion.question_id).finally(() =>
            setActionInProgress(false),
          );
        },
      },
    ]);
  }, [activeQuestion, gameId]);

  const onOpenPhotoViewer = useCallback(() => {
    if (!activeQuestion) return;
    const subject =
      activeSlot?.photo_subject ??
      (activeQuestion.parameters && 'subject' in activeQuestion.parameters
        ? (activeQuestion.parameters as { subject: string }).subject
        : null);
    useGameplayStore.getState().openPhotoViewer({
      questionId: activeQuestion.question_id,
      subject,
      submittedBy: null,
      submittedAt: activeQuestion.submitted_at ?? null,
    });
  }, [activeQuestion, activeSlot]);

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

  const onAsk = useCallback(() => {
    if (!previewQuestion) return;
    Alert.alert('Ask Question', 'Ask this question?', [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Ask',
        onPress: () => {
          const location = useGameplayStore.getState().selfLocation?.coordinates;
          if (!location) {
            Alert.alert('Location Unavailable', 'Cannot determine your position. Try again.');
            return;
          }
          if (previewQuestion.question_type === 'photo') {
            setActionInProgress(true);
            void api
              .POST('/games/{game_id}/questions/photo', {
                params: { path: { game_id: gameId }, header: authHeader() },
                body: { slot_index: previewQuestion.slot_index, location },
              })
              .then(({ error }) => {
                if (error) Alert.alert('Error', 'Failed to ask question.');
              })
              .finally(() => setActionInProgress(false));
            return;
          }
          const path = ASK_PATHS[previewQuestion.question_type as keyof typeof ASK_PATHS];
          if (!path) return;
          setActionInProgress(true);
          void api
            .POST(path, {
              params: { path: { game_id: gameId }, header: authHeader() },
              body: {
                slot_index: previewQuestion.slot_index,
                location,
                custom_distance: previewQuestion.custom_distance ?? null,
              },
            })
            .then(({ error }) => {
              if (error) {
                Alert.alert('Error', 'Failed to ask question.');
              }
              // On success: SSE question_asked event auto-clears previewQuestion
            })
            .finally(() => setActionInProgress(false));
        },
      },
    ]);
  }, [previewQuestion, gameId]);

  const previewSlot = useMemo(() => {
    if (!previewQuestion) return undefined;
    return inventory.find(
      (slot) =>
        slot.question_type === previewQuestion.question_type &&
        slot.slot_index === previewQuestion.slot_index,
    );
  }, [previewQuestion, inventory]);

  const lockInEnabled = useMemo(() => {
    if (!activeQuestion || activeQuestion.question_type !== 'thermometer') return false;
    const seekerQ = activeQuestion as SeekerActiveQuestion;
    // After SSE reconnection, these fields are absent — allow lock-in (server validates on POST).
    if (!seekerQ.seeker_location_start || !seekerQ.parameters) return true;
    if (!selfLocation) return false;
    const params = seekerQ.parameters as ThermometerEventParams;
    const distMeters = haversineMeters(seekerQ.seeker_location_start, selfLocation.coordinates);
    return metersToConvention(distMeters, convention) >= params.min_travel;
  }, [activeQuestion, selfLocation, convention]);

  const travelRemaining = useMemo(() => {
    if (!activeQuestion || activeQuestion.question_type !== 'thermometer') return null;
    const seekerQ = activeQuestion as SeekerActiveQuestion;
    if (!seekerQ.seeker_location_start || !seekerQ.parameters || !selfLocation) return null;
    const params = seekerQ.parameters as ThermometerEventParams;
    const distMeters = haversineMeters(seekerQ.seeker_location_start, selfLocation.coordinates);
    const remaining = Math.max(0, params.min_travel - metersToConvention(distMeters, convention));
    const unit = convention === 'metric' ? 'km' : 'mi';
    return `travel ${remaining.toFixed(1)} ${unit} more`;
  }, [activeQuestion, selfLocation, convention]);

  // Preview state (pre-ask) — triggered by question selection UI
  if (previewQuestion && !activeQuestion) {
    const previewColors = getTypeColors(previewQuestion.question_type);
    const previewLabel = previewQuestion.custom_distance
      ? `${previewQuestion.custom_distance} ${convention === 'metric' ? 'km' : 'mi'}`
      : formatQuestionLabel(previewQuestion.question_type, previewSlot, convention);

    // Tentacles: show POI count or zero-POI warning
    const isTentacles = previewQuestion.question_type === 'tentacles';
    const poiCount = isTentacles && tentaclePois ? tentaclePois.length : null;
    const zeroPoi = poiCount === 0;

    return (
      <View style={styles.container}>
        <MaterialCommunityIcons
          name={questionTypeIcon(previewQuestion.question_type)}
          size={20}
          color={previewColors.onActive}
        />
        {zeroPoi ? (
          <View style={styles.labelColumn}>
            <Text style={[styles.label, { color: previewColors.onActive }]} numberOfLines={1}>
              {previewLabel}
            </Text>
            <Text style={styles.warningText} numberOfLines={1}>
              No {previewSlot?.category?.replaceAll('_', ' ') ?? 'POIs'} in range — hit impossible
            </Text>
          </View>
        ) : (
          <Text style={[styles.label, { color: previewColors.onActive }]} numberOfLines={1}>
            {previewLabel}
            {poiCount !== null && poiCount > 0 ? ` — ${poiCount} in range` : ''}
          </Text>
        )}
        <Pressable
          style={({ pressed }) => [
            styles.button,
            buttonStyle(previewColors.onActive),
            isDisabled && styles.disabled,
            pressed && !isDisabled && buttonPressedStyle(previewColors.onActive),
          ]}
          disabled={isDisabled}
          onPress={onAsk}
        >
          <Text style={[styles.buttonText, { color: previewColors.onActive }]}>Ask</Text>
        </Pressable>
      </View>
    );
  }

  if (!activeQuestion) return null;

  const isThermometerInProgress =
    activeQuestion.question_type === 'thermometer' && activeQuestion.status === 'in_progress';

  // Thermometer in-progress: seeker needs to travel then lock in
  if (isThermometerInProgress) {
    const thermoColors = getTypeColors('thermometer');
    return (
      <View style={styles.container}>
        <MaterialCommunityIcons name="thermometer" size={20} color={thermoColors.onActive} />
        <Text style={[styles.label, { color: thermoColors.onActive }]} numberOfLines={1}>
          {formatQuestionLabel('thermometer', activeSlot, convention)}
          {lockInEnabled
            ? ' — ready to lock in'
            : travelRemaining
              ? ` — ${travelRemaining}`
              : ' — travel to lock in'}
        </Text>
        <Pressable
          style={({ pressed }) => [
            styles.iconButton,
            buttonStyle(thermoColors.onActive),
            (isDisabled || !lockInEnabled) && styles.disabled,
            pressed && !isDisabled && lockInEnabled && buttonPressedStyle(thermoColors.onActive),
          ]}
          disabled={isDisabled || !lockInEnabled}
          onPress={onLockIn}
        >
          <MaterialCommunityIcons name="map-marker-check" size={20} color={thermoColors.onActive} />
        </Pressable>
        <Pressable
          style={({ pressed }) => [
            styles.iconButton,
            buttonStyle(thermoColors.onActive),
            isDisabled && styles.disabled,
            pressed && !isDisabled && buttonPressedStyle(thermoColors.onActive),
          ]}
          disabled={isDisabled}
          onPress={onAbandon}
        >
          <MaterialCommunityIcons name="close" size={20} color={thermoColors.onActive} />
        </Pressable>
      </View>
    );
  }

  // Photo question — answerable: waiting for hider to submit a photo
  if (activeQuestion.question_type === 'photo' && activeQuestion.status === 'answerable') {
    const photoColors = getTypeColors('photo');
    const subjectText = formatQuestionLabel('photo', activeSlot, convention);
    return (
      <View style={styles.container}>
        <MaterialCommunityIcons name="camera" size={20} color={photoColors.onActive} />
        <Text style={[styles.label, { color: photoColors.onActive }]} numberOfLines={1}>
          {subjectText} — waiting for photo...
        </Text>
        <BannerCountdown
          deadlineIso={activeQuestion.question_deadline}
          color={photoColors.onActive}
        />
        <Pressable
          style={({ pressed }) => [
            styles.iconButton,
            buttonStyle(photoColors.onActive),
            isDisabled && styles.disabled,
            pressed && !isDisabled && buttonPressedStyle(photoColors.onActive),
          ]}
          disabled={isDisabled}
          onPress={onAbandon}
        >
          <MaterialCommunityIcons name="close" size={18} color={photoColors.onActive} />
        </Pressable>
      </View>
    );
  }

  // Photo question — submitted: seeker reviews thumbnail (or "null") and accepts/rejects
  if (activeQuestion.question_type === 'photo' && activeQuestion.status === 'submitted') {
    const photoColors = getTypeColors('photo');
    const isNull = activeQuestion.is_null_answer === true;
    const photoUrl = `${API_BASE_URL}/games/${gameId}/questions/${activeQuestion.question_id}/photo`;
    return (
      <View style={styles.container}>
        <MaterialCommunityIcons name="camera" size={20} color={photoColors.onActive} />
        {isNull ? (
          <View style={styles.nullThumbnail}>
            <Text style={styles.nullThumbnailText}>null</Text>
          </View>
        ) : (
          <Pressable onPress={onOpenPhotoViewer}>
            <Image
              source={{ uri: photoUrl, headers: authHeader() }}
              style={styles.thumbnail}
              resizeMode="cover"
            />
          </Pressable>
        )}
        <BannerCountdown
          deadlineIso={activeQuestion.review_deadline}
          color={photoColors.onActive}
        />
        <View style={styles.actions}>
          <Pressable
            style={({ pressed }) => [
              styles.iconButton,
              buttonStyle(photoColors.onActive),
              isDisabled && styles.disabled,
              pressed && !isDisabled && buttonPressedStyle(photoColors.onActive),
            ]}
            disabled={isDisabled}
            onPress={onAcceptPhoto}
          >
            <MaterialCommunityIcons name="check" size={20} color={photoColors.onActive} />
          </Pressable>
          <Pressable
            style={({ pressed }) => [
              styles.iconButton,
              buttonStyle(photoColors.onActive),
              isDisabled && styles.disabled,
              pressed && !isDisabled && buttonPressedStyle(photoColors.onActive),
            ]}
            disabled={isDisabled}
            onPress={onRejectPhoto}
          >
            <MaterialCommunityIcons name="close" size={20} color={photoColors.onActive} />
          </Pressable>
          <Pressable
            style={({ pressed }) => [
              styles.iconButton,
              buttonStyle(photoColors.onActive),
              isDisabled && styles.disabled,
              pressed && !isDisabled && buttonPressedStyle(photoColors.onActive),
            ]}
            disabled={isDisabled}
            onPress={onAbandon}
          >
            <MaterialCommunityIcons
              name="trash-can-outline"
              size={18}
              color={photoColors.onActive}
            />
          </Pressable>
        </View>
      </View>
    );
  }

  // Active question (asked or answerable): waiting for hider to answer
  const activeColors = getTypeColors(activeQuestion.question_type);
  return (
    <View style={styles.container}>
      <MaterialCommunityIcons
        name={questionTypeIcon(activeQuestion.question_type)}
        size={20}
        color={activeColors.onActive}
      />
      <Text style={[styles.label, { color: activeColors.onActive }]} numberOfLines={1}>
        {formatQuestionLabel(activeQuestion.question_type, activeSlot, convention)} — waiting...
      </Text>
      <BannerCountdown
        deadlineIso={activeQuestion.question_deadline}
        color={activeColors.onActive}
      />
      <Pressable
        style={({ pressed }) => [
          styles.iconButton,
          buttonStyle(activeColors.onActive),
          isDisabled && styles.disabled,
          pressed && !isDisabled && buttonPressedStyle(activeColors.onActive),
        ]}
        disabled={isDisabled}
        onPress={onAbandon}
      >
        <MaterialCommunityIcons name="close" size={18} color={activeColors.onActive} />
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
  actions: {
    flexDirection: 'row',
    gap: 8,
    marginLeft: 'auto',
  },
  label: {
    flex: 1,
    color: '#fff',
    fontSize: 13,
    flexShrink: 1,
  },
  labelColumn: {
    flex: 1,
    flexShrink: 1,
    justifyContent: 'center',
  },
  warningText: {
    color: 'rgb(241, 196, 15)',
    fontSize: 11,
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
  buttonText: {
    color: '#fff',
    fontSize: 13,
    fontWeight: '600',
  },
  disabled: {
    opacity: 0.5,
  },
  thumbnail: {
    width: 36,
    height: 36,
    borderRadius: 6,
    backgroundColor: 'rgba(0, 0, 0, 0.15)',
  },
  nullThumbnail: {
    width: 36,
    height: 36,
    borderRadius: 6,
    backgroundColor: 'rgba(0, 0, 0, 0.2)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  nullThumbnailText: {
    color: '#fff',
    fontSize: 11,
    fontWeight: '700',
    fontStyle: 'italic',
  },
});

const EMPTY_INVENTORY: InventorySlotResponse[] = [];
