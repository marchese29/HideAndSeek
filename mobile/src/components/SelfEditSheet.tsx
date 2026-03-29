import { useState } from 'react';
import { Alert, Modal, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';

import { authHeader } from '@/api/auth';
import { api } from '@/api/client';
import type { components } from '@/api/schema';
import { type PlayerColor } from '@/constants/colors';

import { ColorPicker } from './ColorPicker';

type PlayerResponse = components['schemas']['PlayerResponse'];
type PlayerRole = 'hider' | 'seeker';

interface SelfEditSheetProps {
  visible: boolean;
  onClose: () => void;
  player: PlayerResponse;
  takenColors: PlayerColor[];
  gameId: string;
}

export function SelfEditSheet({
  visible,
  onClose,
  player,
  takenColors,
  gameId,
}: SelfEditSheetProps) {
  const [name, setName] = useState(player.name);
  const [selectedColor, setSelectedColor] = useState<PlayerColor>(player.color as PlayerColor);
  const [selectedRole, setSelectedRole] = useState<PlayerRole | null>(
    player.role as PlayerRole | null,
  );

  async function patchPlayer(
    updates: Omit<components['schemas']['PlayerUpdate'], 'device_token_provider'>,
  ) {
    const { error } = await api.PATCH('/games/{game_id}/players/{player_id}', {
      params: {
        path: { game_id: gameId, player_id: player.id },
        header: authHeader(),
      },
      body: { ...updates, device_token_provider: 'apns' },
    });
    if (error) {
      const detail = (error as { detail?: string }).detail;
      Alert.alert('Error', detail ?? 'Failed to update.');
    }
  }

  function handleNameSubmit() {
    const trimmed = name.trim();
    if (trimmed && trimmed !== player.name) {
      void patchPlayer({ name: trimmed });
    }
  }

  function handleColorSelect(color: PlayerColor) {
    setSelectedColor(color);
    void patchPlayer({ color });
  }

  function handleRoleToggle(role: PlayerRole) {
    const newRole = selectedRole === role ? null : role;
    setSelectedRole(newRole);
    void patchPlayer({ role: newRole });
  }

  return (
    <Modal visible={visible} animationType="slide" presentationStyle="pageSheet">
      <View style={styles.container}>
        <View style={styles.header}>
          <Text style={styles.title}>Edit Player</Text>
          <Pressable onPress={onClose}>
            <Text style={styles.done}>Done</Text>
          </Pressable>
        </View>

        <Text style={styles.label}>Name</Text>
        <TextInput
          style={styles.nameInput}
          value={name}
          onChangeText={setName}
          onBlur={handleNameSubmit}
          onSubmitEditing={handleNameSubmit}
          maxLength={30}
        />

        <Text style={styles.label}>Color</Text>
        <ColorPicker
          selectedColor={selectedColor}
          takenColors={takenColors}
          onSelect={handleColorSelect}
        />

        <Text style={styles.label}>Role</Text>
        <View style={styles.roleRow}>
          <Pressable
            style={[styles.roleButton, selectedRole === 'hider' && styles.roleActive]}
            onPress={() => handleRoleToggle('hider')}
          >
            <Text style={[styles.roleText, selectedRole === 'hider' && styles.roleTextActive]}>
              Hider
            </Text>
          </Pressable>
          <Pressable
            style={[styles.roleButton, selectedRole === 'seeker' && styles.roleActive]}
            onPress={() => handleRoleToggle('seeker')}
          >
            <Text style={[styles.roleText, selectedRole === 'seeker' && styles.roleTextActive]}>
              Seeker
            </Text>
          </Pressable>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    padding: 24,
    backgroundColor: '#fff',
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 24,
    paddingTop: 8,
  },
  title: {
    fontSize: 20,
    fontWeight: 'bold',
  },
  done: {
    fontSize: 16,
    fontWeight: '600',
    color: '#3498DB',
  },
  label: {
    fontSize: 14,
    fontWeight: '600',
    color: '#666',
    marginBottom: 8,
    marginTop: 20,
  },
  nameInput: {
    fontSize: 18,
    borderWidth: 2,
    borderColor: '#ddd',
    borderRadius: 12,
    padding: 16,
  },
  roleRow: {
    flexDirection: 'row',
    gap: 12,
  },
  roleButton: {
    flex: 1,
    paddingVertical: 14,
    borderRadius: 12,
    borderWidth: 2,
    borderColor: '#ddd',
    alignItems: 'center',
  },
  roleActive: {
    borderColor: '#3498DB',
    backgroundColor: '#EBF5FB',
  },
  roleText: {
    fontSize: 16,
    fontWeight: '600',
    color: '#888',
  },
  roleTextActive: {
    color: '#3498DB',
  },
});
