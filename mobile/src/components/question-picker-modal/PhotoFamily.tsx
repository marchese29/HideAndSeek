import { MaterialCommunityIcons } from '@expo/vector-icons';
import { FlatList, Pressable, StyleSheet, Text, View } from 'react-native';

import { getTypeColors } from '@/constants/questionColors';
import type { InventorySlotResponse } from '@/types/gameplay';
import { type PhotoSubject, photoSubjectIcon, photoSubjectLabel } from '@/utils/photoSubjects';

interface PhotoFamilyProps {
  slots: InventorySlotResponse[];
  selectedSubject: PhotoSubject | null;
  onSelectSubject: (subject: PhotoSubject | null) => void;
}

export function PhotoFamily({ slots, selectedSubject, onSelectSubject }: PhotoFamilyProps) {
  const photoSlots = slots
    .filter((s) => s.question_type === 'photo' && s.photo_subject)
    .sort((a, b) => a.slot_index - b.slot_index);

  const colors = getTypeColors('photo');

  return (
    <FlatList
      data={photoSlots}
      keyExtractor={(item) => item.photo_subject ?? String(item.slot_index)}
      contentContainerStyle={styles.list}
      renderItem={({ item }) => {
        const subject = item.photo_subject as PhotoSubject;
        const selected = selectedSubject === subject;
        return (
          <Pressable
            style={({ pressed }) => [
              styles.row,
              selected && { borderColor: 'rgba(255,255,255,0.6)' },
              pressed && styles.rowPressed,
            ]}
            onPress={() => onSelectSubject(selected ? null : subject)}
          >
            <View style={[styles.iconSquare, { backgroundColor: colors.active }]}>
              <MaterialCommunityIcons
                name={photoSubjectIcon(subject)}
                size={24}
                color={colors.onActive}
              />
            </View>
            <Text style={styles.label} numberOfLines={2}>
              {photoSubjectLabel(subject)}
            </Text>
            {item.ask_count > 0 && (
              <View style={styles.badge}>
                <Text style={styles.badgeText}>x{item.ask_count + 1}</Text>
              </View>
            )}
          </Pressable>
        );
      }}
    />
  );
}

const styles = StyleSheet.create({
  list: {
    paddingHorizontal: 16,
    paddingVertical: 12,
    gap: 8,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 10,
    paddingHorizontal: 12,
    borderRadius: 10,
    backgroundColor: '#2C2C2E',
    borderWidth: 2,
    borderColor: 'transparent',
    gap: 12,
    marginBottom: 4,
  },
  rowPressed: {
    opacity: 0.7,
  },
  iconSquare: {
    width: 44,
    height: 44,
    borderRadius: 8,
    alignItems: 'center',
    justifyContent: 'center',
  },
  label: {
    flex: 1,
    fontSize: 15,
    fontWeight: '500',
    color: '#fff',
  },
  badge: {
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 10,
    backgroundColor: 'rgba(255,255,255,0.15)',
  },
  badgeText: {
    fontSize: 12,
    fontWeight: '600',
    color: 'rgba(255,255,255,0.85)',
  },
});
