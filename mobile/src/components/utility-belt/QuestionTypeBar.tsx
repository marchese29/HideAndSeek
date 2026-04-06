import { MaterialCommunityIcons } from '@expo/vector-icons';
import { memo } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

interface QuestionTypeBarProps {
  onSelectType: (type: string) => void;
  selectedType: string | null;
  disabled: boolean;
}

interface TypeColors {
  active: string;
  inactive: string;
}

const TYPE_COLORS: Record<string, TypeColors> = {
  radar: { active: 'rgb(245, 121, 59)', inactive: 'rgb(242, 181, 150)' },
  thermometer: { active: 'rgb(255, 191, 65)', inactive: 'rgb(248, 215, 152)' },
  matching: { active: 'rgb(33, 47, 64)', inactive: 'rgb(135, 143, 151)' },
  measuring: { active: 'rgb(77, 162, 100)', inactive: 'rgb(158, 201, 169)' },
};

const QUESTION_TYPES: {
  type: string;
  icon: keyof typeof MaterialCommunityIcons.glyphMap;
  label: string;
}[] = [
  { type: 'radar', icon: 'radar', label: 'Radar' },
  { type: 'thermometer', icon: 'thermometer', label: 'Thermo' },
  { type: 'matching', icon: 'map-marker-multiple', label: 'Match' },
  { type: 'measuring', icon: 'ruler', label: 'Measure' },
];

export const QuestionTypeBar = memo(function QuestionTypeBar({
  onSelectType,
  selectedType,
  disabled,
}: QuestionTypeBarProps) {
  // Split into rows of 2
  const rows: (typeof QUESTION_TYPES)[] = [];
  for (let i = 0; i < QUESTION_TYPES.length; i += 2) {
    rows.push(QUESTION_TYPES.slice(i, i + 2));
  }

  return (
    <View style={styles.container}>
      {rows.map((row, rowIndex) => (
        <View key={rowIndex} style={styles.row}>
          {row.map(({ type, icon, label }) => {
            const isSelected = type === selectedType;
            const colors = TYPE_COLORS[type];
            const bg = disabled ? colors.inactive : colors.active;
            return (
              <Pressable
                key={type}
                style={({ pressed }) => [
                  styles.button,
                  { backgroundColor: bg },
                  isSelected && styles.selected,
                  disabled && styles.disabled,
                  pressed && !disabled && styles.pressed,
                ]}
                onPress={() => onSelectType(type)}
                disabled={disabled}
              >
                <MaterialCommunityIcons name={icon} size={16} color="#fff" />
                <Text style={styles.label}>{label}</Text>
              </Pressable>
            );
          })}
        </View>
      ))}
    </View>
  );
});

const styles = StyleSheet.create({
  container: {
    flex: 1,
    justifyContent: 'center',
    paddingHorizontal: 6,
    gap: 4,
  },
  row: {
    flexDirection: 'row',
    justifyContent: 'space-evenly',
    gap: 4,
  },
  button: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 4,
    paddingHorizontal: 6,
    borderRadius: 6,
    borderWidth: 1.5,
    borderColor: 'transparent',
    gap: 4,
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
    fontWeight: '700',
    textTransform: 'uppercase',
    letterSpacing: 0.3,
  },
});
