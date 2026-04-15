import { MaterialCommunityIcons } from '@expo/vector-icons';
import { memo, useState } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';

import { MoreModal } from '@/components/more-modal';

interface BeltActionsProps {
  disabled: boolean;
}

export const BeltActions = memo(function BeltActions({ disabled }: BeltActionsProps) {
  const [modalVisible, setModalVisible] = useState(false);

  return (
    <View style={styles.container}>
      <Pressable
        style={({ pressed }) => [
          styles.button,
          disabled && styles.disabled,
          pressed && !disabled && styles.pressed,
        ]}
        onPress={() => setModalVisible(true)}
        disabled={disabled}
      >
        <MaterialCommunityIcons name="dots-vertical" size={20} color="#fff" />
      </Pressable>

      <MoreModal visible={modalVisible} onClose={() => setModalVisible(false)} />
    </View>
  );
});

const styles = StyleSheet.create({
  container: {
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#1C1C1E',
    padding: 8,
    borderTopLeftRadius: 10,
    borderBottomLeftRadius: 10,
  },
  button: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: 8,
    borderRadius: 8,
    borderWidth: 1,
    backgroundColor: 'rgba(255, 255, 255, 0.06)',
    borderColor: 'rgba(255, 255, 255, 0.12)',
  },
  pressed: {
    backgroundColor: 'rgba(255, 255, 255, 0.22)',
  },
  disabled: {
    opacity: 0.5,
  },
});
