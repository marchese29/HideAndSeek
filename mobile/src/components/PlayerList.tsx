import { useState } from 'react';
import { Alert, FlatList, Pressable, StyleSheet, Text, View } from 'react-native';

import { authHeader } from '@/api/auth';
import { api } from '@/api/client';
import type { components } from '@/api/schema';
import { type PlayerColor } from '@/constants/colors';

import { PlayerCard } from './PlayerCard';
import { SelfEditSheet } from './SelfEditSheet';

type PlayerResponse = components['schemas']['PlayerResponse'];
type GameResponse = components['schemas']['GameResponse'];

interface PlayerListProps {
  game: GameResponse;
  playerId: string;
  disabled?: boolean;
}

export function PlayerList({ game, playerId, disabled }: PlayerListProps) {
  const [editVisible, setEditVisible] = useState(false);
  const isHost = game.host_player_id === playerId;
  const selfPlayer = game.players.find((p) => p.id === playerId);
  const takenColors = game.players.map((p) => p.color as PlayerColor);

  function handleKick(player: PlayerResponse) {
    Alert.alert('Remove Player', `Remove ${player.name} from the game?`, [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Remove',
        style: 'destructive',
        onPress: () => {
          void api.DELETE('/games/{game_id}/players/{player_id}', {
            params: {
              path: { game_id: game.id, player_id: player.id },
              header: authHeader(),
            },
          });
        },
      },
    ]);
  }

  function renderItem({ item: player }: { item: PlayerResponse }) {
    const isSelf = player.id === playerId;
    const playerIsHost = player.id === game.host_player_id;

    return (
      <View style={styles.row}>
        <Pressable
          style={styles.cardWrapper}
          onPress={isSelf ? () => setEditVisible(true) : undefined}
          disabled={disabled}
        >
          <PlayerCard player={player} isHost={playerIsHost} isSelf={isSelf} />
        </Pressable>
        {isHost && !isSelf && (
          <Pressable
            style={styles.kickButton}
            onPress={() => handleKick(player)}
            disabled={disabled}
          >
            <Text style={styles.kickText}>X</Text>
          </Pressable>
        )}
      </View>
    );
  }

  return (
    <>
      <FlatList
        data={game.players}
        keyExtractor={(player) => player.id}
        renderItem={renderItem}
        contentContainerStyle={styles.list}
      />
      {selfPlayer && (
        <SelfEditSheet
          visible={editVisible}
          onClose={() => setEditVisible(false)}
          player={selfPlayer}
          takenColors={takenColors}
          gameId={game.id}
        />
      )}
    </>
  );
}

const styles = StyleSheet.create({
  list: {
    padding: 16,
    gap: 8,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  cardWrapper: {
    flex: 1,
  },
  kickButton: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: '#FDEDEC',
    justifyContent: 'center',
    alignItems: 'center',
  },
  kickText: {
    color: '#E74C3C',
    fontWeight: 'bold',
    fontSize: 14,
  },
});
