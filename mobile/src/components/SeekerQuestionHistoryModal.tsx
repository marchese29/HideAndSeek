import { MaterialCommunityIcons } from '@expo/vector-icons';
import { useEffect, useMemo, useRef, useState } from 'react';
import { Modal, PanResponder, Pressable, StyleSheet, Text, View } from 'react-native';
import MapView from 'react-native-maps';

import { getTypeColors } from '@/constants/questionColors';
import { type PhotoViewerState, useGameplayStore } from '@/stores/gameplayStore';
import type { GameInfo, GeoJSONGeometry, SeekerQuestionHistoryEntry } from '@/types/gameplay';
import { regionFromBoundary } from '@/utils/geo';
import { geometryDifference } from '@/utils/geometryDifference';

import { BoundaryOverlay } from './BoundaryOverlay';
import { ExclusionOverlay } from './ExclusionOverlay';
import { QuestionHistoryRow } from './QuestionHistoryRow';
import { TransitRoute } from './TransitRoute';

const START_DOT_COLOR = 'rgba(255,255,255,0.35)';
const ACTIVE_RING_COLOR = '#fff';

interface SeekerQuestionHistoryModalProps {
  visible: boolean;
  onClose: () => void;
  questions: SeekerQuestionHistoryEntry[];
  gameInfo: GameInfo;
  gameId: string;
}

export function SeekerQuestionHistoryModal({
  visible,
  onClose,
  questions,
  gameInfo,
  gameId,
}: SeekerQuestionHistoryModalProps) {
  const unit = gameInfo.distance_convention === 'metric' ? 'km' : 'mi';
  const initialRegion = useMemo(() => regionFromBoundary(gameInfo.boundary), [gameInfo.boundary]);

  const n = questions.length;

  // 0 = before any questions; 1..N = after question at index (position-1).
  const [position, setPosition] = useState(n);

  // Re-seat position when the modal opens so it always lands on the most recent
  // question (or Start, if there are none yet). Scrubber state isn't meaningful
  // across opens — reviewing is a fresh action each time.
  useEffect(() => {
    if (visible) setPosition(n);
  }, [visible, n]);

  const currentEntry = position >= 1 ? questions[position - 1] : null;
  const priorCumulative: GeoJSONGeometry | null =
    position >= 2 ? (questions[position - 2].total_exclusion ?? null) : null;
  const currentCumulative: GeoJSONGeometry | null = currentEntry?.total_exclusion ?? null;

  const delta = useMemo(
    () => geometryDifference(currentCumulative, priorCumulative),
    [currentCumulative, priorCumulative],
  );

  const pendingPhotoViewerRef = useRef<PhotoViewerState | null>(null);

  const handleDismiss = () => {
    onClose();
    const pending = pendingPhotoViewerRef.current;
    if (pending) {
      pendingPhotoViewerRef.current = null;
      useGameplayStore.getState().openPhotoViewer(pending);
    }
  };

  const typeColors = currentEntry ? getTypeColors(currentEntry.question_type) : null;
  const deltaFill = typeColors
    ? `rgba(${typeColors.rgb[0]}, ${typeColors.rgb[1]}, ${typeColors.rgb[2]}, 0.55)`
    : undefined;
  const deltaStroke = typeColors
    ? `rgba(${typeColors.rgb[0]}, ${typeColors.rgb[1]}, ${typeColors.rgb[2]}, 0.9)`
    : undefined;

  return (
    <Modal
      visible={visible}
      animationType="slide"
      presentationStyle="pageSheet"
      onRequestClose={onClose}
      onDismiss={handleDismiss}
    >
      <View style={styles.container}>
        <View style={styles.header}>
          <Text style={styles.title}>Question History</Text>
          <Pressable style={styles.closeButton} onPress={onClose}>
            <MaterialCommunityIcons name="close" size={22} color="rgba(255,255,255,0.6)" />
          </Pressable>
        </View>

        {n === 0 ? (
          <View style={styles.emptyContainer}>
            <Text style={styles.emptyText}>
              No questions answered yet.{'\n'}Ask a question to see how it narrows things down.
            </Text>
          </View>
        ) : (
          <>
            <View style={styles.mapWrapper}>
              <MapView style={StyleSheet.absoluteFill} initialRegion={initialRegion}>
                <BoundaryOverlay boundary={gameInfo.boundary} />
                {gameInfo.routes.map((route) => (
                  <TransitRoute key={route.id} route={route} stops={gameInfo.stops} />
                ))}
                {priorCumulative && (
                  <ExclusionOverlay key={`cum-${position}`} exclusion={priorCumulative} />
                )}
                {delta && deltaFill && deltaStroke && (
                  <ExclusionOverlay
                    key={`delta-${position}`}
                    exclusion={delta}
                    fillColor={deltaFill}
                    strokeColor={deltaStroke}
                    strokeWidth={1.5}
                    zIndex={2100}
                  />
                )}
              </MapView>
            </View>

            <Scrubber questions={questions} position={position} onChange={setPosition} />

            <View style={styles.cardSlot}>
              {currentEntry ? (
                <QuestionHistoryRow
                  entry={currentEntry}
                  unit={unit}
                  gameId={gameId}
                  onPhotoTap={(params) => {
                    pendingPhotoViewerRef.current = {
                      questionId: params.questionId,
                      subject: params.subject,
                      submittedBy: params.submittedBy,
                      submittedAt: params.submittedAt,
                    };
                    onClose();
                  }}
                />
              ) : (
                <View style={styles.startCard}>
                  <Text style={styles.startLabel}>Start</Text>
                  <Text style={styles.startHint}>Before any questions were answered.</Text>
                </View>
              )}
            </View>
          </>
        )}
      </View>
    </Modal>
  );
}

interface ScrubberProps {
  questions: SeekerQuestionHistoryEntry[];
  position: number;
  onChange: (pos: number) => void;
}

function Scrubber({ questions, position, onChange }: ScrubberProps) {
  const n = questions.length;
  const trackLayoutRef = useRef<{ pageX: number; width: number } | null>(null);
  const trackRef = useRef<View | null>(null);
  const positionRef = useRef(position);
  positionRef.current = position;
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  const measureTrack = () => {
    trackRef.current?.measure((_x, _y, width, _h, pageX) => {
      trackLayoutRef.current = { pageX, width };
    });
  };

  const onLayout = () => {
    measureTrack();
  };

  const panResponder = useMemo(
    () =>
      PanResponder.create({
        onStartShouldSetPanResponder: () => true,
        onMoveShouldSetPanResponder: () => true,
        onPanResponderGrant: (evt) => {
          // Re-measure on grant — modal slide transitions can change absolute layout.
          measureTrack();
          const layout = trackLayoutRef.current;
          if (!layout || layout.width <= 0) return;
          const localX = evt.nativeEvent.pageX - layout.pageX;
          const next = xToPosition(localX, layout.width, n);
          if (next !== positionRef.current) onChangeRef.current(next);
        },
        onPanResponderMove: (evt) => {
          const layout = trackLayoutRef.current;
          if (!layout || layout.width <= 0) return;
          const localX = evt.nativeEvent.pageX - layout.pageX;
          const next = xToPosition(localX, layout.width, n);
          if (next !== positionRef.current) onChangeRef.current(next);
        },
      }),
    [n],
  );

  const stops = n + 1;

  return (
    <View style={styles.scrubberWrapper}>
      <View
        ref={trackRef}
        onLayout={onLayout}
        style={styles.scrubberTrack}
        collapsable={false}
        {...panResponder.panHandlers}
      >
        <View style={styles.scrubberLine} pointerEvents="none" />
        {Array.from({ length: stops }).map((_, i) => {
          const isActive = i === position;
          const isStart = i === 0;
          const entry = isStart ? null : questions[i - 1];
          const color = entry ? getTypeColors(entry.question_type).active : START_DOT_COLOR;
          return (
            <View
              key={i}
              pointerEvents="none"
              style={[
                styles.scrubberDot,
                { backgroundColor: color },
                isActive && styles.scrubberDotActive,
              ]}
            />
          );
        })}
      </View>
      <View style={styles.scrubberLabels} pointerEvents="none">
        <Text style={styles.scrubberLabel}>Start</Text>
        <Text style={styles.scrubberLabel}>{n >= 1 ? `Q${questions[n - 1].sequence}` : ''}</Text>
      </View>
    </View>
  );
}

function xToPosition(x: number, width: number, n: number): number {
  if (n === 0) return 0;
  const clamped = Math.max(0, Math.min(width, x));
  const step = width / n;
  return Math.max(0, Math.min(n, Math.round(clamped / step)));
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
    color: '#fff',
  },
  closeButton: {
    padding: 4,
  },
  emptyContainer: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 32,
  },
  emptyText: {
    fontSize: 15,
    color: 'rgba(255,255,255,0.5)',
    textAlign: 'center',
    lineHeight: 22,
  },
  mapWrapper: {
    flex: 1,
    marginHorizontal: 12,
    marginBottom: 12,
    borderRadius: 12,
    overflow: 'hidden',
    backgroundColor: '#000',
  },
  scrubberWrapper: {
    paddingHorizontal: 20,
    paddingVertical: 4,
  },
  scrubberTrack: {
    height: 44,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    position: 'relative',
  },
  scrubberLine: {
    position: 'absolute',
    left: 6,
    right: 6,
    top: 21,
    height: 2,
    backgroundColor: 'rgba(255,255,255,0.2)',
    borderRadius: 1,
  },
  scrubberDot: {
    width: 14,
    height: 14,
    borderRadius: 7,
  },
  scrubberDotActive: {
    width: 20,
    height: 20,
    borderRadius: 10,
    borderWidth: 2,
    borderColor: ACTIVE_RING_COLOR,
  },
  scrubberLabels: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingHorizontal: 4,
    marginTop: 2,
  },
  scrubberLabel: {
    fontSize: 12,
    fontWeight: '500',
    color: 'rgba(255,255,255,0.5)',
  },
  cardSlot: {
    paddingHorizontal: 16,
    minHeight: 80,
    justifyContent: 'center',
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: 'rgba(255,255,255,0.1)',
  },
  startCard: {},
  startLabel: {
    fontSize: 15,
    fontWeight: '600',
    color: '#fff',
  },
  startHint: {
    fontSize: 13,
    color: 'rgba(255,255,255,0.5)',
    marginTop: 2,
  },
});
