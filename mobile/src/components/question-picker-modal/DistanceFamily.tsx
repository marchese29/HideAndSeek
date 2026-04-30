import { useEffect, useMemo } from 'react';
import { StyleSheet, View } from 'react-native';
import MapView from 'react-native-maps';

import { useGameInfo } from '@/hooks/useGameInfo';
import { usePreviewBoundaryFor } from '@/hooks/usePreviewBoundary';
import { useGameplayStore } from '@/stores/gameplayStore';
import type { InventorySlotResponse } from '@/types/gameplay';
import { regionFromBoundary } from '@/utils/geo';

import { BoundaryOverlay } from '../BoundaryOverlay';
import { ExclusionOverlay } from '../ExclusionOverlay';
import { PreviewBoundaryOverlay } from '../PreviewBoundaryOverlay';
import { TransitRoute } from '../TransitRoute';
import { DistanceScrubber } from './DistanceScrubber';

interface DistanceFamilyProps {
  questionType: 'radar' | 'thermometer';
  gameId: string;
  slots: InventorySlotResponse[];
  selectedSlot: InventorySlotResponse | null;
  customValue: number | null;
  onSelect: (slot: InventorySlotResponse, customValue: number | null) => void;
  onInteract: () => void;
}

export function DistanceFamily({
  questionType,
  gameId,
  slots,
  selectedSlot,
  customValue,
  onSelect,
  onInteract,
}: DistanceFamilyProps) {
  const { gameInfo } = useGameInfo(gameId);

  const presetSlots = useMemo(
    () =>
      slots
        .filter((s) => s.question_type === questionType && s.distance != null)
        .sort((a, b) => (a.distance ?? 0) - (b.distance ?? 0)),
    [slots, questionType],
  );

  const customSlot = useMemo(
    () => slots.find((s) => s.question_type === questionType && s.distance === null) ?? null,
    [slots, questionType],
  );

  // Default to smallest preset on first open if nothing is selected yet.
  useEffect(() => {
    if (selectedSlot != null) return;
    if (presetSlots.length === 0) return;
    onSelect(presetSlots[0], customValue);
    // We intentionally don't depend on `customValue` / `onSelect` to avoid
    // re-defaulting after the user clears a selection — the parent owns
    // selection lifecycle.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedSlot, presetSlots]);

  const initialRegion = useMemo(
    () => (gameInfo ? regionFromBoundary(gameInfo.boundary) : null),
    [gameInfo],
  );

  const previewInput = useMemo(() => {
    if (questionType !== 'radar') return null;
    if (!selectedSlot) return null;
    return {
      questionType,
      slotIndex: selectedSlot.slot_index,
      customDistance: customValue,
    };
  }, [questionType, selectedSlot, customValue]);

  const { boundary } = usePreviewBoundaryFor(previewInput);

  const totalExclusion = useGameplayStore((s) =>
    s.status === 'connected' && s.role === 'seeker' ? s.state.total_exclusion : null,
  );

  if (!gameInfo || !initialRegion) {
    return <View style={styles.container} />;
  }

  return (
    <View style={styles.container}>
      <View style={styles.mapWrapper}>
        <MapView style={StyleSheet.absoluteFill} initialRegion={initialRegion}>
          <BoundaryOverlay boundary={gameInfo.boundary} />
          {gameInfo.routes.map((route) => (
            <TransitRoute key={route.id} route={route} stops={gameInfo.stops} />
          ))}
          <ExclusionOverlay exclusion={totalExclusion} />
          {boundary && questionType === 'radar' && (
            <PreviewBoundaryOverlay
              boundary={boundary}
              questionType={questionType}
              variant="active"
            />
          )}
        </MapView>
      </View>
      <DistanceScrubber
        presets={presetSlots}
        customSlot={customSlot}
        selectedSlot={selectedSlot}
        customValue={customValue}
        convention={gameInfo.distance_convention}
        questionType={questionType}
        onSelectPreset={(slot) => {
          onInteract();
          onSelect(slot, customValue);
        }}
        onSelectCustom={() => {
          if (!customSlot || customValue == null) return;
          onInteract();
          onSelect(customSlot, customValue);
        }}
        onConfirmCustom={(value) => {
          if (!customSlot) return;
          onInteract();
          onSelect(customSlot, value);
        }}
        onClearCustom={() => {
          onInteract();
          if (presetSlots.length > 0) {
            onSelect(presetSlots[0], null);
          }
        }}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  mapWrapper: {
    flex: 1,
    marginHorizontal: 12,
    marginTop: 12,
    borderRadius: 12,
    overflow: 'hidden',
    backgroundColor: '#000',
  },
});
