import { StyleSheet, Text, View } from 'react-native';

import type { components } from '@/api/schema';
import { COLOR_HEX, type PlayerColor } from '@/constants/colors';

type PlayerResponse = components['schemas']['PlayerResponse'];

interface PlayerCardProps {
  player: PlayerResponse;
  isHost: boolean;
  isSelf: boolean;
}

export function PlayerCard({ player, isHost, isSelf }: PlayerCardProps) {
  return (
    <View style={[styles.card, isSelf && styles.selfCard]}>
      <View
        style={[styles.colorSwatch, { backgroundColor: COLOR_HEX[player.color as PlayerColor] }]}
      />
      <View style={styles.info}>
        <View style={styles.nameRow}>
          <Text style={styles.name}>{player.name}</Text>
          {isHost && <Text style={styles.hostBadge}>Host</Text>}
        </View>
        <Text style={styles.role}>{player.role ?? 'No role'}</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 12,
    backgroundColor: '#f8f8f8',
    borderRadius: 10,
    gap: 12,
  },
  selfCard: {
    borderWidth: 2,
    borderColor: '#3498DB',
  },
  colorSwatch: {
    width: 32,
    height: 32,
    borderRadius: 16,
  },
  info: {
    flex: 1,
  },
  nameRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  name: {
    fontSize: 16,
    fontWeight: '600',
  },
  hostBadge: {
    fontSize: 12,
    fontWeight: '600',
    color: '#F39C12',
    backgroundColor: '#FEF3E2',
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
    overflow: 'hidden',
  },
  role: {
    fontSize: 13,
    color: '#888',
    marginTop: 2,
  },
});
