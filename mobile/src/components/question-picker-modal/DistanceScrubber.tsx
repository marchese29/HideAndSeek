import { MaterialCommunityIcons } from '@expo/vector-icons';
import { memo, useCallback, useMemo, useRef, useState } from 'react';
import { PanResponder, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';

import { getTypeColors } from '@/constants/questionColors';
import type { InventorySlotResponse } from '@/types/gameplay';
import { validateCustomDistance } from '@/utils/distance';

interface DistanceScrubberProps {
  presets: InventorySlotResponse[];
  customSlot: InventorySlotResponse | null;
  selectedSlot: InventorySlotResponse | null;
  customValue: number | null;
  convention: string;
  questionType: string;
  onSelectPreset: (slot: InventorySlotResponse) => void;
  onSelectCustom: () => void;
  onConfirmCustom: (value: number) => void;
  onClearCustom: () => void;
}

interface LockSpec {
  ratio: number;
  presetIndex: number;
}

function presetRatios(count: number): number[] {
  if (count <= 1) return [0];
  return Array.from({ length: count }, (_, i) => i / (count - 1));
}

export const DistanceScrubber = memo(function DistanceScrubber({
  presets,
  customSlot,
  selectedSlot,
  customValue,
  convention,
  questionType,
  onSelectPreset,
  onSelectCustom,
  onConfirmCustom,
  onClearCustom,
}: DistanceScrubberProps) {
  const colors = getTypeColors(questionType);
  const unit = convention === 'metric' ? 'km' : 'mi';

  const locks = useMemo<LockSpec[]>(
    () =>
      presetRatios(presets.length).map((ratio, i) => ({
        ratio,
        presetIndex: i,
      })),
    [presets.length],
  );

  const trackRef = useRef<View | null>(null);
  const trackLayoutRef = useRef<{ pageX: number; width: number } | null>(null);
  const lastDispatchRef = useRef<number | null>(null);

  const measureTrack = () => {
    trackRef.current?.measure((_x, _y, width, _h, pageX) => {
      trackLayoutRef.current = { pageX, width };
    });
  };

  const handleTouch = useCallback(
    (pageX: number) => {
      const layout = trackLayoutRef.current;
      if (!layout || layout.width <= 0) return;
      const localX = Math.max(0, Math.min(layout.width, pageX - layout.pageX));
      const ratio = localX / layout.width;
      let bestIdx = 0;
      let bestDist = Infinity;
      for (let i = 0; i < locks.length; i++) {
        const d = Math.abs(locks[i].ratio - ratio);
        if (d < bestDist) {
          bestDist = d;
          bestIdx = i;
        }
      }
      const target = locks[bestIdx];
      if (lastDispatchRef.current === target.presetIndex) return;
      lastDispatchRef.current = target.presetIndex;
      onSelectPreset(presets[target.presetIndex]);
    },
    [locks, presets, onSelectPreset],
  );

  const panResponder = useMemo(
    () =>
      PanResponder.create({
        onStartShouldSetPanResponder: () => true,
        onMoveShouldSetPanResponder: () => true,
        onPanResponderGrant: (evt) => {
          measureTrack();
          lastDispatchRef.current = null;
          handleTouch(evt.nativeEvent.pageX);
        },
        onPanResponderMove: (evt) => {
          handleTouch(evt.nativeEvent.pageX);
        },
        onPanResponderRelease: () => {
          lastDispatchRef.current = null;
        },
        onPanResponderTerminate: () => {
          lastDispatchRef.current = null;
        },
      }),
    [handleTouch],
  );

  const customSelected =
    customSlot != null && selectedSlot != null && selectedSlot.slot_index === customSlot.slot_index;

  const selectedPresetIndex = useMemo<number>(() => {
    if (!selectedSlot || customSelected) return -1;
    return presets.findIndex((p) => p.slot_index === selectedSlot.slot_index);
  }, [selectedSlot, customSelected, presets]);

  return (
    <View style={styles.wrapper}>
      <View
        ref={trackRef}
        onLayout={measureTrack}
        style={styles.track}
        collapsable={false}
        {...panResponder.panHandlers}
      >
        <View style={styles.trackLine} pointerEvents="none" />
        {locks.map((lock) => {
          const isSelected = lock.presetIndex === selectedPresetIndex;
          const left = `${lock.ratio * 100}%` as const;
          const presetSlot = presets[lock.presetIndex];
          const askCount = presetSlot.ask_count ?? 0;
          const dotColor = isSelected ? colors.active : colors.inactive;
          return (
            <View
              key={`preset:${lock.presetIndex}`}
              pointerEvents="none"
              style={[styles.lockCol, { left }]}
            >
              {askCount > 0 && (
                <View style={styles.badge}>
                  <Text style={styles.badgeText}>x{askCount + 1}</Text>
                </View>
              )}
              <View
                style={[
                  styles.dot,
                  { backgroundColor: dotColor },
                  isSelected && styles.dotSelected,
                ]}
              />
              <Text style={styles.distanceLabel} numberOfLines={1}>
                {presetSlot.distance ?? ''} {unit}
              </Text>
            </View>
          );
        })}
      </View>
      <CustomChip
        customValue={customValue}
        unit={unit}
        canEdit={customSlot != null}
        askCount={customSlot?.ask_count ?? 0}
        isSelected={customSelected}
        accentColor={colors.active}
        onAccentColor={colors.onActive}
        onSelect={onSelectCustom}
        onConfirm={onConfirmCustom}
        onClear={onClearCustom}
      />
    </View>
  );
});

interface CustomChipProps {
  customValue: number | null;
  unit: string;
  canEdit: boolean;
  askCount: number;
  isSelected: boolean;
  accentColor: string;
  onAccentColor: string;
  onSelect: () => void;
  onConfirm: (value: number) => void;
  onClear: () => void;
}

function CustomChip({
  customValue,
  unit,
  canEdit,
  askCount,
  isSelected,
  accentColor,
  onAccentColor,
  onSelect,
  onConfirm,
  onClear,
}: CustomChipProps) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState('');
  const valid = validateCustomDistance(text);

  if (!canEdit) return null;

  const open = () => {
    setText(customValue != null ? String(customValue) : '');
    setEditing(true);
  };

  const submit = () => {
    if (!valid) return;
    onConfirm(Number(text));
    setEditing(false);
  };

  const cancel = () => {
    setEditing(false);
    setText('');
  };

  if (editing) {
    return (
      <View style={styles.chipEditing}>
        <TextInput
          style={styles.input}
          value={text}
          onChangeText={setText}
          keyboardType="decimal-pad"
          placeholder="0.0"
          placeholderTextColor="rgba(255,255,255,0.4)"
          autoFocus
          returnKeyType="done"
          onSubmitEditing={submit}
        />
        <Text style={styles.unit}>{unit}</Text>
        <Pressable
          onPress={submit}
          disabled={!valid}
          style={({ pressed }) => [
            styles.iconButton,
            valid ? styles.confirmButton : styles.confirmButtonDisabled,
            pressed && valid && styles.confirmPressed,
          ]}
        >
          <MaterialCommunityIcons
            name="check"
            size={18}
            color={valid ? '#fff' : 'rgba(255,255,255,0.4)'}
          />
        </Pressable>
        <Pressable
          onPress={cancel}
          style={({ pressed }) => [
            styles.iconButton,
            styles.cancelButton,
            pressed && styles.cancelPressed,
          ]}
        >
          <MaterialCommunityIcons name="close" size={18} color="rgba(255,255,255,0.85)" />
        </Pressable>
      </View>
    );
  }

  if (customValue == null) {
    return (
      <Pressable
        onPress={open}
        style={({ pressed }) => [styles.chip, pressed && styles.chipPressed]}
      >
        <MaterialCommunityIcons name="plus" size={18} color="rgba(255,255,255,0.85)" />
        <Text style={styles.chipText}>Custom</Text>
        {askCount > 0 && (
          <View style={styles.inlineBadge}>
            <Text style={styles.badgeText}>x{askCount + 1}</Text>
          </View>
        )}
      </Pressable>
    );
  }

  const filledStyle = isSelected
    ? [styles.chipFilled, { backgroundColor: accentColor, borderColor: accentColor }]
    : styles.chipFilled;
  const textColor = isSelected ? onAccentColor : 'rgba(255,255,255,0.85)';
  const iconColor = isSelected ? onAccentColor : 'rgba(255,255,255,0.85)';

  return (
    <View style={filledStyle}>
      <Pressable
        onPress={onSelect}
        style={({ pressed }) => [styles.chipBody, pressed && styles.chipPressed]}
      >
        <Text style={[styles.chipText, { color: textColor }]}>
          Custom: {customValue} {unit}
        </Text>
        {askCount > 0 && (
          <View style={[styles.inlineBadge, isSelected && { backgroundColor: 'rgba(0,0,0,0.15)' }]}>
            <Text style={[styles.badgeText, { color: textColor }]}>x{askCount + 1}</Text>
          </View>
        )}
      </Pressable>
      <Pressable
        onPress={open}
        style={({ pressed }) => [styles.chipIconCell, pressed && styles.chipPressed]}
      >
        <MaterialCommunityIcons name="pencil" size={18} color={iconColor} />
      </Pressable>
      <Pressable
        onPress={onClear}
        style={({ pressed }) => [styles.chipIconCell, pressed && styles.chipPressed]}
      >
        <MaterialCommunityIcons name="close" size={18} color={iconColor} />
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  wrapper: {
    paddingHorizontal: 24,
    paddingTop: 12,
    paddingBottom: 16,
    gap: 12,
  },
  track: {
    height: 80,
    justifyContent: 'center',
    position: 'relative',
  },
  trackLine: {
    position: 'absolute',
    left: 0,
    right: 0,
    top: 39,
    height: 2,
    backgroundColor: 'rgba(255,255,255,0.2)',
    borderRadius: 1,
  },
  lockCol: {
    position: 'absolute',
    top: 0,
    width: 64,
    marginLeft: -32,
    alignItems: 'center',
  },
  dot: {
    width: 18,
    height: 18,
    borderRadius: 9,
    borderWidth: 2,
    borderColor: 'transparent',
    marginTop: 30,
  },
  dotSelected: {
    borderColor: 'rgba(255,255,255,0.85)',
    width: 22,
    height: 22,
    borderRadius: 11,
    marginTop: 28,
  },
  badge: {
    position: 'absolute',
    top: 8,
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 8,
    backgroundColor: 'rgba(255,255,255,0.15)',
  },
  inlineBadge: {
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 8,
    backgroundColor: 'rgba(255,255,255,0.15)',
  },
  badgeText: {
    fontSize: 10,
    color: 'rgba(255,255,255,0.85)',
    fontWeight: '600',
  },
  distanceLabel: {
    marginTop: 6,
    fontSize: 11,
    color: 'rgba(255,255,255,0.7)',
    fontWeight: '500',
  },
  chip: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#2C2C2E',
    borderRadius: 10,
    paddingVertical: 10,
    paddingHorizontal: 14,
    gap: 8,
  },
  chipFilled: {
    flexDirection: 'row',
    alignItems: 'stretch',
    backgroundColor: '#2C2C2E',
    borderRadius: 10,
    borderWidth: 1,
    borderColor: 'transparent',
    overflow: 'hidden',
  },
  chipBody: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 10,
    paddingHorizontal: 14,
    gap: 8,
  },
  chipIconCell: {
    paddingHorizontal: 12,
    alignItems: 'center',
    justifyContent: 'center',
  },
  chipPressed: {
    opacity: 0.7,
  },
  chipText: {
    color: 'rgba(255,255,255,0.85)',
    fontSize: 14,
    fontWeight: '500',
  },
  chipEditing: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#2C2C2E',
    borderRadius: 10,
    paddingVertical: 6,
    paddingHorizontal: 10,
    gap: 6,
  },
  input: {
    flex: 1,
    backgroundColor: '#1C1C1E',
    borderRadius: 8,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.1)',
    paddingHorizontal: 10,
    paddingVertical: 6,
    fontSize: 16,
    color: '#fff',
    minWidth: 60,
  },
  unit: {
    color: 'rgba(255,255,255,0.85)',
    fontSize: 14,
    fontWeight: '600',
    marginRight: 4,
  },
  iconButton: {
    paddingHorizontal: 10,
    paddingVertical: 8,
    borderRadius: 8,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  confirmButton: {
    backgroundColor: 'rgba(52, 152, 219, 0.4)',
    borderColor: 'rgba(52, 152, 219, 0.6)',
  },
  confirmButtonDisabled: {
    backgroundColor: 'rgba(255,255,255,0.05)',
    borderColor: 'rgba(255,255,255,0.1)',
  },
  confirmPressed: {
    backgroundColor: 'rgba(52, 152, 219, 0.6)',
  },
  cancelButton: {
    backgroundColor: 'rgba(255,255,255,0.08)',
    borderColor: 'rgba(255,255,255,0.15)',
  },
  cancelPressed: {
    backgroundColor: 'rgba(255,255,255,0.18)',
  },
});
