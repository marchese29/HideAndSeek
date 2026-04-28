import { MaterialCommunityIcons } from '@expo/vector-icons';
import * as ImageManipulator from 'expo-image-manipulator';
import * as ImagePicker from 'expo-image-picker';
import { memo, useCallback, useEffect, useMemo, useState } from 'react';
import { Alert, Image, Linking, Pressable, StyleSheet, Text, View } from 'react-native';

import { authHeader } from '@/api/auth';
import { API_BASE_URL } from '@/api/client';
import {
  answerQuestion,
  type PhotoApiResult,
  type PickedAsset,
  randomizeQuestion,
  submitNullPhoto,
  submitQueuedPhoto,
  unqueuePhoto,
  uploadPhoto,
  vetoQuestion,
} from '@/api/questions';
import { getTypeColors } from '@/constants/questionColors';
import { useGameInfo } from '@/hooks/useGameInfo';
import { useAppStore } from '@/store';
import { useGameplayStore } from '@/stores/gameplayStore';
import { useToastStore } from '@/stores/toastStore';
import type { HiderActiveQuestion } from '@/types/gameplay';
import { photoSubjectLabel } from '@/utils/photoSubjects';

import { BannerCountdown } from './BannerCountdown';

/** Well-known computed_answer values → human-readable labels. */
const ANSWER_LABELS: Record<string, string> = {
  yes: 'Yes',
  no: 'No',
  closer: 'Closer',
  farther: 'Farther',
  miss: 'Miss',
};

function formatAnswerLabel(answer: string, featureNames: Map<string, string>): string {
  if (answer in ANSWER_LABELS) return ANSWER_LABELS[answer];
  const name = featureNames.get(answer);
  if (name) return name;
  return answer
    .split('-')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ');
}

interface HiderBannerProps {
  activeQuestion: HiderActiveQuestion;
  computedAnswer: string | null;
  stationElectionStatus: string | null;
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

function buttonStyle(onActive: string, variant: 'answer' | 'powerUp') {
  const dark = onActive !== '#fff';
  if (variant === 'powerUp') {
    return {
      backgroundColor: dark ? 'rgba(0, 0, 0, 0.08)' : 'rgba(255, 255, 255, 0.15)',
      borderColor: dark ? 'rgba(0, 0, 0, 0.15)' : 'rgba(255, 255, 255, 0.3)',
    };
  }
  return {
    backgroundColor: dark ? 'rgba(0, 0, 0, 0.1)' : 'rgba(255, 255, 255, 0.2)',
    borderColor: dark ? 'rgba(0, 0, 0, 0.2)' : 'rgba(255, 255, 255, 0.4)',
  };
}

function buttonPressedStyle(onActive: string, variant: 'answer' | 'powerUp') {
  const dark = onActive !== '#fff';
  if (variant === 'powerUp') {
    return { backgroundColor: dark ? 'rgba(0, 0, 0, 0.18)' : 'rgba(255, 255, 255, 0.3)' };
  }
  return { backgroundColor: dark ? 'rgba(0, 0, 0, 0.2)' : 'rgba(255, 255, 255, 0.35)' };
}

/** Detect a directly-uploadable asset (server only accepts image/jpeg or image/png). */
function detectNativeType(asset: ImagePicker.ImagePickerAsset): 'image/jpeg' | 'image/png' | null {
  const mime = asset.mimeType?.toLowerCase();
  if (mime === 'image/jpeg' || mime === 'image/jpg') return 'image/jpeg';
  if (mime === 'image/png') return 'image/png';
  if (!mime) {
    const ext = (asset.fileName ?? asset.uri).split('.').pop()?.toLowerCase();
    if (ext === 'jpg' || ext === 'jpeg') return 'image/jpeg';
    if (ext === 'png') return 'image/png';
  }
  return null;
}

function deriveAssetName(asset: ImagePicker.ImagePickerAsset, type: string): string {
  if (asset.fileName) return asset.fileName;
  const ext = type === 'image/png' ? 'png' : 'jpg';
  return `photo.${ext}`;
}

/**
 * Normalize a picker asset to a server-compatible upload payload.
 * JPEG/PNG pass through; anything else (e.g. iOS HEIC/HEIF) is transcoded to JPEG.
 */
async function normalizeAsset(asset: ImagePicker.ImagePickerAsset): Promise<PickedAsset> {
  const native = detectNativeType(asset);
  if (native) {
    return { uri: asset.uri, name: deriveAssetName(asset, native), type: native };
  }
  const result = await ImageManipulator.manipulateAsync(asset.uri, [], {
    compress: 0.9,
    format: ImageManipulator.SaveFormat.JPEG,
  });
  return { uri: result.uri, name: deriveAssetName(asset, 'image/jpeg'), type: 'image/jpeg' };
}

async function ensurePhotoPermission(): Promise<boolean> {
  let perm = await ImagePicker.getMediaLibraryPermissionsAsync();
  if (perm.status === 'granted') return true;
  if (perm.canAskAgain) {
    perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (perm.status === 'granted') return true;
  }
  Alert.alert(
    'Photo Access Required',
    'HideAndSeek needs access to your photo library to submit photos. Open Settings to enable it.',
    [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Open Settings', onPress: () => void Linking.openSettings() },
    ],
  );
  return false;
}

export const HiderBanner = memo(function HiderBanner({
  activeQuestion,
  computedAnswer,
  stationElectionStatus,
  disabled,
  gameId,
}: HiderBannerProps) {
  const isAmbiguous = stationElectionStatus === 'ambiguous';
  const [actionInProgress, setActionInProgress] = useState(false);
  const [localPick, setLocalPick] = useState<PickedAsset | null>(null);
  const isDisabled = disabled || actionInProgress;

  const { gameInfo } = useGameInfo(gameId);
  const colors = getTypeColors(activeQuestion.question_type);
  const selfPlayerId = useAppStore((s) => s.playerId);
  const hiders = useGameplayStore((s) =>
    s.status === 'connected' && s.role === 'hider' ? s.state.hiders : EMPTY_HIDERS,
  );

  const featureNames = useMemo(() => {
    const map = new Map<string, string>();
    if (gameInfo?.features) {
      for (const f of gameInfo.features) {
        map.set(f.stable_id, f.name);
      }
    }
    return map;
  }, [gameInfo?.features]);

  const answerLabel = useMemo(() => {
    if (!computedAnswer || computedAnswer === 'null') return null;
    return formatAnswerLabel(computedAnswer, featureNames);
  }, [computedAnswer, featureNames]);

  // Clear local pick whenever the active question's identity / status / queued state changes.
  useEffect(() => {
    setLocalPick(null);
  }, [activeQuestion.question_id, activeQuestion.status, activeQuestion.photo_queued_by]);

  const handlePhotoResult = useCallback((result: PhotoApiResult) => {
    if (result.ok) return;
    if (result.status === 409) {
      setLocalPick(null);
      useToastStore
        .getState()
        .push({ message: 'Another hider already submitted.', severity: 'info' });
      return;
    }
    Alert.alert('Upload Failed', result.detail);
  }, []);

  const onPickPhoto = useCallback(async () => {
    if (!(await ensurePhotoPermission())) return;
    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ['images'],
      quality: 1,
    });
    if (result.canceled || result.assets.length === 0) return;
    try {
      const picked = await normalizeAsset(result.assets[0]);
      setLocalPick(picked);
    } catch (err) {
      Alert.alert('Photo Error', err instanceof Error ? err.message : 'Could not process photo.');
    }
  }, []);

  const onCommit = useCallback(
    (submit: boolean) => {
      if (!localPick) return;
      setActionInProgress(true);
      void uploadPhoto(gameId, activeQuestion.question_id, localPick, { submit })
        .then(handlePhotoResult)
        .finally(() => setActionInProgress(false));
    },
    [localPick, gameId, activeQuestion.question_id, handlePhotoResult],
  );

  const onSubmitQueued = useCallback(() => {
    setActionInProgress(true);
    void submitQueuedPhoto(gameId, activeQuestion.question_id)
      .then(handlePhotoResult)
      .finally(() => setActionInProgress(false));
  }, [gameId, activeQuestion.question_id, handlePhotoResult]);

  const onReplace = useCallback(async () => {
    if (!(await ensurePhotoPermission())) return;
    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ['images'],
      quality: 1,
    });
    if (result.canceled || result.assets.length === 0) return;
    let picked: PickedAsset;
    try {
      picked = await normalizeAsset(result.assets[0]);
    } catch (err) {
      Alert.alert('Photo Error', err instanceof Error ? err.message : 'Could not process photo.');
      return;
    }
    setActionInProgress(true);
    void uploadPhoto(gameId, activeQuestion.question_id, picked, { submit: false })
      .then(handlePhotoResult)
      .finally(() => setActionInProgress(false));
  }, [gameId, activeQuestion.question_id, handlePhotoResult]);

  const onUnqueue = useCallback(() => {
    setActionInProgress(true);
    void unqueuePhoto(gameId, activeQuestion.question_id)
      .then((result) => {
        // 409 silent (auto-submit may have raced).
        if (!result.ok && result.status !== 409) {
          Alert.alert('Could Not Unqueue', result.detail);
        }
      })
      .finally(() => setActionInProgress(false));
  }, [gameId, activeQuestion.question_id]);

  const onSubmitNull = useCallback(() => {
    Alert.alert(
      'Submit Null?',
      "Submitting null tells the seeker you can't get this photo. This counts as your answer.",
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Submit Null',
          style: 'destructive',
          onPress: () => {
            setActionInProgress(true);
            void submitNullPhoto(gameId, activeQuestion.question_id)
              .then(handlePhotoResult)
              .finally(() => setActionInProgress(false));
          },
        },
      ],
    );
  }, [gameId, activeQuestion.question_id, handlePhotoResult]);

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
        text: 'Randomize',
        onPress: () => {
          Alert.alert('Randomize', 'Replace this question with a random one of the same type?', [
            { text: 'Cancel', style: 'cancel' },
            {
              text: 'Randomize',
              onPress: () => {
                setActionInProgress(true);
                void randomizeQuestion(gameId, activeQuestion.question_id)
                  .then((result) => {
                    if (!result.ok) {
                      Alert.alert('Cannot Randomize', result.detail);
                    }
                  })
                  .finally(() => setActionInProgress(false));
              },
            },
          ]);
        },
      },
    ]);
  }, [gameId, activeQuestion.question_id]);

  // Photo questions branch off entirely.
  const isPhoto = activeQuestion.question_type === 'photo';
  const isPhotoAnswerable = isPhoto && activeQuestion.status === 'answerable';
  const hasQueued = isPhotoAnswerable && activeQuestion.photo_queued_by != null;
  const hasLocalPick = isPhotoAnswerable && localPick != null;

  // Resolve photo subject text via three-tier fallback.
  const photoSubjectText = useMemo(() => {
    if (!isPhoto) return '';
    const fromParams =
      activeQuestion.parameters && activeQuestion.parameters.type === 'photo'
        ? activeQuestion.parameters.subject
        : null;
    const subject = fromParams ?? activeQuestion.photo_subject ?? null;
    return subject ? photoSubjectLabel(subject) : 'Photo';
  }, [isPhoto, activeQuestion.parameters, activeQuestion.photo_subject]);

  const queuedByLabel = useMemo(() => {
    if (!hasQueued) return '';
    const queuedBy = activeQuestion.photo_queued_by;
    if (!queuedBy) return '';
    if (queuedBy === selfPlayerId) return 'Queued by you';
    const name = hiders.find((p) => p.id === queuedBy)?.name;
    return name ? `Queued by ${name}` : 'Queued';
  }, [hasQueued, activeQuestion.photo_queued_by, selfPlayerId, hiders]);

  const onOpenViewer = useCallback(() => {
    if (!isPhoto) return;
    useGameplayStore.getState().openPhotoViewer({
      questionId: activeQuestion.question_id,
      subject: photoSubjectText,
      submittedBy: activeQuestion.photo_queued_by ?? null,
      submittedAt: activeQuestion.submitted_at ?? activeQuestion.photo_uploaded_at ?? null,
    });
  }, [
    isPhoto,
    activeQuestion.question_id,
    activeQuestion.photo_queued_by,
    activeQuestion.submitted_at,
    activeQuestion.photo_uploaded_at,
    photoSubjectText,
  ]);

  const isThermometerPreLockIn =
    activeQuestion.question_type === 'thermometer' &&
    (activeQuestion.status === 'asked' || activeQuestion.status === 'in_progress');

  // Thermometer pre-lock-in: type-colored background, no actions
  if (isThermometerPreLockIn) {
    return (
      <View style={styles.container}>
        <MaterialCommunityIcons name="thermometer" size={20} color={colors.onActive} />
        <Text style={[styles.label, { color: colors.onActive }]} numberOfLines={1}>
          {isAmbiguous
            ? 'Pick A Hiding Zone First!'
            : `Waiting for lock-in${answerLabel ? ` (${answerLabel})` : ''}`}
        </Text>
      </View>
    );
  }

  // ── Photo branches ─────────────────────────────────────────────────────────

  // D — Submitted: thumbnail or null placeholder, review countdown, no actions.
  if (isPhoto && activeQuestion.status === 'submitted') {
    const isNull = activeQuestion.is_null_answer === true;
    const thumbUrl = `${API_BASE_URL}/games/${gameId}/questions/${activeQuestion.question_id}/photo`;
    return (
      <View style={styles.container}>
        <MaterialCommunityIcons name="camera" size={20} color={colors.onActive} />
        {isNull ? (
          <View style={styles.nullThumbnail}>
            <Text style={styles.nullThumbnailText}>null</Text>
          </View>
        ) : (
          <Pressable onPress={onOpenViewer}>
            <Image
              source={{ uri: thumbUrl, headers: authHeader() }}
              style={styles.thumbnail}
              resizeMode="cover"
            />
          </Pressable>
        )}
        <Text style={[styles.label, { color: colors.onActive }]} numberOfLines={1}>
          Submitted — waiting for review...
        </Text>
        <BannerCountdown deadlineIso={activeQuestion.review_deadline} color={colors.onActive} />
      </View>
    );
  }

  // B — Local pick preview: Submit Now / Queue / Replace / Cancel.
  if (hasLocalPick && localPick) {
    return (
      <View style={styles.container}>
        <MaterialCommunityIcons name="camera" size={20} color={colors.onActive} />
        <Image source={{ uri: localPick.uri }} style={styles.thumbnail} resizeMode="cover" />
        <Text
          style={[styles.label, styles.labelGrow, { color: colors.onActive }]}
          numberOfLines={1}
        >
          {photoSubjectText}
        </Text>
        <Pressable
          style={({ pressed }) => [
            styles.iconButton,
            buttonStyle(colors.onActive, 'answer'),
            isDisabled && styles.disabled,
            pressed && !isDisabled && buttonPressedStyle(colors.onActive, 'answer'),
          ]}
          disabled={isDisabled}
          onPress={() => onCommit(true)}
        >
          <MaterialCommunityIcons name="send" size={18} color={colors.onActive} />
        </Pressable>
        <Pressable
          style={({ pressed }) => [
            styles.iconButton,
            buttonStyle(colors.onActive, 'answer'),
            isDisabled && styles.disabled,
            pressed && !isDisabled && buttonPressedStyle(colors.onActive, 'answer'),
          ]}
          disabled={isDisabled}
          onPress={() => onCommit(false)}
        >
          <MaterialCommunityIcons name="timer-sand" size={18} color={colors.onActive} />
        </Pressable>
        <Pressable
          style={({ pressed }) => [
            styles.iconButton,
            buttonStyle(colors.onActive, 'powerUp'),
            isDisabled && styles.disabled,
            pressed && !isDisabled && buttonPressedStyle(colors.onActive, 'powerUp'),
          ]}
          disabled={isDisabled}
          onPress={() => setLocalPick(null)}
        >
          <MaterialCommunityIcons name="close" size={18} color={colors.onActive} />
        </Pressable>
      </View>
    );
  }

  // C — Queued: thumbnail (tap viewer) + subject + "Queued by ..." + countdown + actions.
  if (hasQueued) {
    const cacheBust = encodeURIComponent(activeQuestion.photo_uploaded_at ?? '');
    const thumbUrl = `${API_BASE_URL}/games/${gameId}/questions/${activeQuestion.question_id}/photo?v=${cacheBust}`;
    return (
      <View style={styles.container}>
        <MaterialCommunityIcons name="camera" size={20} color={colors.onActive} />
        <Pressable onPress={onOpenViewer}>
          <Image
            source={{ uri: thumbUrl, headers: authHeader() }}
            style={styles.thumbnail}
            resizeMode="cover"
          />
        </Pressable>
        <View style={styles.labelColumn}>
          <Text style={[styles.label, { color: colors.onActive }]} numberOfLines={1}>
            {photoSubjectText}
          </Text>
          {queuedByLabel ? (
            <Text style={[styles.subLabel, { color: colors.onActive }]} numberOfLines={1}>
              {queuedByLabel}
            </Text>
          ) : null}
        </View>
        <BannerCountdown deadlineIso={activeQuestion.question_deadline} color={colors.onActive} />
        <Pressable
          style={({ pressed }) => [
            styles.iconButton,
            buttonStyle(colors.onActive, 'answer'),
            isDisabled && styles.disabled,
            pressed && !isDisabled && buttonPressedStyle(colors.onActive, 'answer'),
          ]}
          disabled={isDisabled}
          onPress={onSubmitQueued}
        >
          <MaterialCommunityIcons name="send" size={18} color={colors.onActive} />
        </Pressable>
        <Pressable
          style={({ pressed }) => [
            styles.iconButton,
            buttonStyle(colors.onActive, 'powerUp'),
            isDisabled && styles.disabled,
            pressed && !isDisabled && buttonPressedStyle(colors.onActive, 'powerUp'),
          ]}
          disabled={isDisabled}
          onPress={() => void onReplace()}
        >
          <MaterialCommunityIcons name="image-refresh-outline" size={18} color={colors.onActive} />
        </Pressable>
        <Pressable
          style={({ pressed }) => [
            styles.iconButton,
            buttonStyle(colors.onActive, 'powerUp'),
            isDisabled && styles.disabled,
            pressed && !isDisabled && buttonPressedStyle(colors.onActive, 'powerUp'),
          ]}
          disabled={isDisabled}
          onPress={onUnqueue}
        >
          <MaterialCommunityIcons name="close" size={18} color={colors.onActive} />
        </Pressable>
      </View>
    );
  }

  // A — Asked (no queue, no local pick): Pick / Null / Power-Up.
  if (isPhotoAnswerable) {
    return (
      <View style={styles.container}>
        <MaterialCommunityIcons name="camera" size={20} color={colors.onActive} />
        <Text style={[styles.label, { color: colors.onActive }]} numberOfLines={1}>
          {photoSubjectText}
        </Text>
        <BannerCountdown deadlineIso={activeQuestion.question_deadline} color={colors.onActive} />
        <Pressable
          style={({ pressed }) => [
            styles.button,
            styles.answerButton,
            buttonStyle(colors.onActive, 'answer'),
            (isDisabled || isAmbiguous) && styles.disabled,
            pressed && !isDisabled && !isAmbiguous && buttonPressedStyle(colors.onActive, 'answer'),
          ]}
          disabled={isDisabled || isAmbiguous}
          onPress={() => void onPickPhoto()}
        >
          <Text style={[styles.buttonText, { color: colors.onActive }]} numberOfLines={1}>
            {isAmbiguous ? 'Pick A Hiding Zone First!' : 'Pick Photo'}
          </Text>
        </Pressable>
        <Pressable
          style={({ pressed }) => [
            styles.iconButton,
            buttonStyle(colors.onActive, 'powerUp'),
            (isDisabled || isAmbiguous) && styles.disabled,
            pressed &&
              !isDisabled &&
              !isAmbiguous &&
              buttonPressedStyle(colors.onActive, 'powerUp'),
          ]}
          disabled={isDisabled || isAmbiguous}
          onPress={onSubmitNull}
        >
          <MaterialCommunityIcons name="cancel" size={16} color={colors.onActive} />
        </Pressable>
        <Pressable
          style={({ pressed }) => [
            styles.button,
            styles.powerUpButton,
            buttonStyle(colors.onActive, 'powerUp'),
            (isDisabled || isAmbiguous) && styles.disabled,
            pressed &&
              !isDisabled &&
              !isAmbiguous &&
              buttonPressedStyle(colors.onActive, 'powerUp'),
          ]}
          disabled={isDisabled || isAmbiguous}
          onPress={onPowerUp}
        >
          <MaterialCommunityIcons name="lightning-bolt" size={16} color={colors.onActive} />
        </Pressable>
      </View>
    );
  }

  // ── Other question types ────────────────────────────────────────────────────

  const answerDisabled = isDisabled || isAmbiguous || !answerLabel;

  return (
    <View style={styles.container}>
      <MaterialCommunityIcons
        name={questionTypeIcon(activeQuestion.question_type)}
        size={20}
        color={colors.onActive}
      />
      <BannerCountdown deadlineIso={activeQuestion.question_deadline} color={colors.onActive} />
      <Pressable
        style={({ pressed }) => [
          styles.button,
          styles.answerButton,
          buttonStyle(colors.onActive, 'answer'),
          answerDisabled && styles.disabled,
          pressed && !answerDisabled && buttonPressedStyle(colors.onActive, 'answer'),
        ]}
        disabled={answerDisabled}
        onPress={onAnswer}
      >
        <Text style={[styles.buttonText, { color: colors.onActive }]} numberOfLines={1}>
          {isAmbiguous ? 'Pick A Hiding Zone First!' : (answerLabel ?? 'Answer')}
        </Text>
      </Pressable>
      <Pressable
        style={({ pressed }) => [
          styles.button,
          styles.powerUpButton,
          buttonStyle(colors.onActive, 'powerUp'),
          (isDisabled || isAmbiguous) && styles.disabled,
          pressed && !isDisabled && !isAmbiguous && buttonPressedStyle(colors.onActive, 'powerUp'),
        ]}
        disabled={isDisabled || isAmbiguous}
        onPress={onPowerUp}
      >
        <MaterialCommunityIcons name="lightning-bolt" size={16} color={colors.onActive} />
      </Pressable>
    </View>
  );
});

const EMPTY_HIDERS: { id: string; name: string }[] = [];

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
    fontSize: 14,
  },
  labelGrow: {
    flex: 1,
  },
  labelColumn: {
    flex: 1,
    flexShrink: 1,
    justifyContent: 'center',
  },
  subLabel: {
    fontSize: 11,
    opacity: 0.85,
  },
  button: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 8,
    borderWidth: 1,
  },
  answerButton: {
    flex: 1,
  },
  powerUpButton: {
    paddingHorizontal: 8,
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
    fontSize: 13,
    fontWeight: '600',
    textAlign: 'center',
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
