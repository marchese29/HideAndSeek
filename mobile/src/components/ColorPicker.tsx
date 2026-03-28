import { Pressable, StyleSheet, View } from 'react-native';

import { COLOR_HEX, type PlayerColor } from '@/constants/colors';

const ALL_COLORS = Object.keys(COLOR_HEX) as PlayerColor[];

interface ColorPickerProps {
  selectedColor: PlayerColor;
  takenColors: PlayerColor[];
  onSelect: (color: PlayerColor) => void;
}

export function ColorPicker({ selectedColor, takenColors, onSelect }: ColorPickerProps) {
  return (
    <View style={styles.grid}>
      {ALL_COLORS.map((color) => {
        const taken = takenColors.includes(color) && color !== selectedColor;
        const selected = color === selectedColor;
        return (
          <Pressable
            key={color}
            style={[styles.swatch, selected && styles.selected, taken && styles.taken]}
            onPress={() => !taken && onSelect(color)}
            disabled={taken}
          >
            <View style={[styles.colorCircle, { backgroundColor: COLOR_HEX[color] }]} />
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  grid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  swatch: {
    width: 48,
    height: 48,
    borderRadius: 24,
    justifyContent: 'center',
    alignItems: 'center',
    borderWidth: 3,
    borderColor: 'transparent',
  },
  selected: {
    borderColor: '#2C3E50',
  },
  taken: {
    opacity: 0.25,
  },
  colorCircle: {
    width: 36,
    height: 36,
    borderRadius: 18,
  },
});
