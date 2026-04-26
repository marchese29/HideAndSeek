import { memo } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { getTypeColors } from '@/constants/questionColors';
import type { InventorySlotResponse } from '@/types/gameplay';
import { photoSubjectShortLabel } from '@/utils/photoSubjects';

interface ParamPickerProps {
  slots: InventorySlotResponse[];
  convention: string;
  questionType: string;
  selectedSlotIndex: number | null;
  onSelectSlot: (slot: InventorySlotResponse) => void;
  onCustomPress: () => void;
  disabled: boolean;
}

function formatSlotLabel(slot: InventorySlotResponse, convention: string): string {
  if (slot.question_type === 'photo' && slot.photo_subject) {
    return photoSubjectShortLabel(slot.photo_subject);
  }
  const unit = convention === 'metric' ? 'km' : 'mi';
  // Tentacles: both category and distance are set
  if (slot.category && slot.distance !== null) {
    const label = slot.category.replaceAll('_', ' ');
    return `${label} ${slot.distance} ${unit}`;
  }
  if (slot.distance !== null) {
    return `${slot.distance} ${unit}`;
  }
  if (slot.category) {
    return slot.category.replaceAll('_', ' ');
  }
  return 'Custom';
}

function isCustomSlot(slot: InventorySlotResponse): boolean {
  return (
    slot.distance === null &&
    slot.category === null &&
    (slot.question_type === 'radar' || slot.question_type === 'thermometer')
  );
}

/** Split an array into chunks of the given size. */
function chunk<T>(arr: T[], size: number): T[][] {
  const rows: T[][] = [];
  for (let i = 0; i < arr.length; i += size) {
    rows.push(arr.slice(i, i + size));
  }
  return rows;
}

export const ParamPicker = memo(function ParamPicker({
  slots,
  convention,
  questionType,
  selectedSlotIndex,
  onSelectSlot,
  onCustomPress,
  disabled,
}: ParamPickerProps) {
  const itemsPerRow = Math.ceil(slots.length / 4);
  const rows = chunk(slots, itemsPerRow);
  const colors = getTypeColors(questionType);

  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      contentContainerStyle={styles.scrollContent}
    >
      <View style={styles.grid}>
        {rows.map((row, rowIndex) => (
          <View key={rowIndex} style={styles.row}>
            {row.map((slot) => {
              const isCustom = isCustomSlot(slot);
              const isSelected = slot.slot_index === selectedSlotIndex;
              const bg = isSelected ? colors.active : colors.inactive;
              return (
                <Pressable
                  key={`${slot.question_type}-${slot.slot_index}`}
                  style={({ pressed }) => [
                    styles.pill,
                    { backgroundColor: bg },
                    isSelected && styles.selected,
                    disabled && styles.disabled,
                    pressed && !disabled && styles.pressed,
                  ]}
                  onPress={() => (isCustom ? onCustomPress() : onSelectSlot(slot))}
                  disabled={disabled}
                >
                  <Text style={styles.label} numberOfLines={1}>
                    {formatSlotLabel(slot, convention)}
                  </Text>
                  {slot.ask_count > 0 && (
                    <Text style={styles.badgeText}>x{slot.ask_count + 1}</Text>
                  )}
                </Pressable>
              );
            })}
          </View>
        ))}
      </View>
    </ScrollView>
  );
});

const styles = StyleSheet.create({
  scrollContent: {
    flexGrow: 1,
    justifyContent: 'center',
    paddingHorizontal: 6,
  },
  grid: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'space-evenly',
  },
  row: {
    flexDirection: 'row',
    justifyContent: 'center',
    gap: 3,
  },
  pill: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 2,
    paddingHorizontal: 9,
    borderRadius: 10,
    borderWidth: 1.5,
    borderColor: 'transparent',
    gap: 3,
  },
  selected: {
    borderColor: 'rgba(255, 255, 255, 0.6)',
  },
  pressed: {
    opacity: 0.8,
  },
  disabled: {
    opacity: 0.5,
  },
  label: {
    color: '#fff',
    fontSize: 10,
    fontWeight: '600',
  },
  badgeText: {
    color: 'rgba(255, 255, 255, 0.7)',
    fontSize: 9,
    fontWeight: '500',
  },
});
