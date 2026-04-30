import { MaterialCommunityIcons } from '@expo/vector-icons';
import { memo, useCallback, useState } from 'react';
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';

import { validateCustomDistance } from '@/utils/distance';

interface CustomDistanceInputProps {
  onSubmit: (distance: number) => void;
  onCancel: () => void;
  convention: string;
}

export const CustomDistanceInput = memo(function CustomDistanceInput({
  onSubmit,
  onCancel,
  convention,
}: CustomDistanceInputProps) {
  const [text, setText] = useState('');
  const valid = validateCustomDistance(text);
  const unit = convention === 'metric' ? 'km' : 'mi';

  const handleSubmit = useCallback(() => {
    if (!valid) return;
    onSubmit(Number(text));
  }, [valid, text, onSubmit]);

  return (
    <View style={styles.container}>
      <TextInput
        style={styles.input}
        value={text}
        onChangeText={setText}
        keyboardType="decimal-pad"
        placeholder="0.0"
        placeholderTextColor="#95A5A6"
        autoFocus
        returnKeyType="done"
        onSubmitEditing={handleSubmit}
      />
      <Text style={styles.unit}>{unit}</Text>
      <Pressable
        style={({ pressed }) => [
          styles.iconButton,
          styles.confirmButton,
          !valid && styles.disabled,
          pressed && valid && styles.confirmPressed,
        ]}
        onPress={handleSubmit}
        disabled={!valid}
      >
        <MaterialCommunityIcons name="check" size={18} color={valid ? '#fff' : '#95A5A6'} />
      </Pressable>
      <Pressable
        style={({ pressed }) => [
          styles.iconButton,
          styles.cancelButton,
          pressed && styles.cancelPressed,
        ]}
        onPress={onCancel}
      >
        <MaterialCommunityIcons name="close" size={18} color="#2C3E50" />
      </Pressable>
    </View>
  );
});

const styles = StyleSheet.create({
  container: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 12,
    gap: 6,
  },
  input: {
    flex: 1,
    backgroundColor: '#fff',
    borderRadius: 8,
    borderWidth: 1,
    borderColor: 'rgba(44, 62, 80, 0.2)',
    paddingHorizontal: 10,
    paddingVertical: 6,
    fontSize: 16,
    color: '#2C3E50',
    minWidth: 60,
  },
  unit: {
    color: '#2C3E50',
    fontSize: 14,
    fontWeight: '600',
  },
  iconButton: {
    padding: 8,
    borderRadius: 8,
    borderWidth: 1,
  },
  confirmButton: {
    backgroundColor: 'rgba(52, 152, 219, 0.3)',
    borderColor: 'rgba(52, 152, 219, 0.5)',
  },
  confirmPressed: {
    backgroundColor: 'rgba(52, 152, 219, 0.5)',
  },
  cancelButton: {
    backgroundColor: 'rgba(44, 62, 80, 0.08)',
    borderColor: 'rgba(44, 62, 80, 0.15)',
  },
  cancelPressed: {
    backgroundColor: 'rgba(44, 62, 80, 0.15)',
  },
  disabled: {
    opacity: 0.5,
  },
});
