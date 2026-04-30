import { MaterialCommunityIcons } from '@expo/vector-icons';
import { Pressable, ScrollView, StyleSheet, Text } from 'react-native';

export type MenuOption = 'stats' | 'preferences' | 'leave' | 'pause-game' | 'end-game' | 'kick';

interface MoreMenuProps {
  isHost: boolean;
  gameIsActive: boolean;
  isHostPaused: boolean;
  hasOtherPlayers: boolean;
  onSelect: (option: MenuOption) => void;
}

interface MenuItem {
  key: MenuOption;
  label: string;
  icon: React.ComponentProps<typeof MaterialCommunityIcons>['name'];
  destructive?: boolean;
}

export function MoreMenu({
  isHost,
  gameIsActive,
  isHostPaused,
  hasOtherPlayers,
  onSelect,
}: MoreMenuProps) {
  const items: MenuItem[] = [
    { key: 'stats', label: 'Stats', icon: 'chart-bar' },
    { key: 'preferences', label: 'Preferences', icon: 'cog-outline' },
    { key: 'leave', label: 'Leave Game', icon: 'exit-run', destructive: true },
  ];

  if (isHost && gameIsActive && !isHostPaused) {
    items.push({
      key: 'pause-game',
      label: 'Pause Game',
      icon: 'pause-circle-outline',
    });
  }
  if (isHost && gameIsActive) {
    items.push({
      key: 'end-game',
      label: 'End Game',
      icon: 'stop-circle-outline',
      destructive: true,
    });
  }
  if (isHost && hasOtherPlayers) {
    items.push({
      key: 'kick',
      label: 'Kick Player',
      icon: 'account-remove-outline',
      destructive: true,
    });
  }

  return (
    <ScrollView style={styles.list} contentContainerStyle={styles.listContent}>
      {items.map((item, index) => (
        <Pressable
          key={item.key}
          style={({ pressed }) => [
            styles.row,
            index === 0 && styles.rowFirst,
            index === items.length - 1 && styles.rowLast,
            pressed && styles.rowPressed,
          ]}
          onPress={() => onSelect(item.key)}
        >
          <MaterialCommunityIcons
            name={item.icon}
            size={22}
            color={item.destructive ? '#E74C3C' : '#fff'}
          />
          <Text style={[styles.label, item.destructive && styles.labelDestructive]}>
            {item.label}
          </Text>
          <MaterialCommunityIcons name="chevron-right" size={20} color="rgba(255,255,255,0.3)" />
        </Pressable>
      ))}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  list: {
    flex: 1,
  },
  listContent: {
    padding: 16,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 14,
    paddingVertical: 14,
    paddingHorizontal: 16,
    backgroundColor: 'rgba(255, 255, 255, 0.06)',
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: 'rgba(255, 255, 255, 0.12)',
  },
  rowFirst: {
    borderTopLeftRadius: 12,
    borderTopRightRadius: 12,
  },
  rowLast: {
    borderBottomLeftRadius: 12,
    borderBottomRightRadius: 12,
    borderBottomWidth: 0,
  },
  rowPressed: {
    backgroundColor: 'rgba(255, 255, 255, 0.12)',
  },
  label: {
    flex: 1,
    fontSize: 16,
    color: '#fff',
  },
  labelDestructive: {
    color: '#E74C3C',
  },
});
