import { useMemo } from 'react';
import MapView from 'react-native-maps';

import { BoundaryOverlay } from '@/components/BoundaryOverlay';
import { PlayerPin } from '@/components/PlayerPin';
import { TransitRoute } from '@/components/TransitRoute';
import type { GamePlayer, HiderGameState, SeekerGameState } from '@/types/gameplay';
import { regionFromBoundary } from '@/utils/geo';

interface GameMapProps {
  role: 'hider' | 'seeker';
  state: HiderGameState | SeekerGameState;
}

interface PlayerEntry {
  player: GamePlayer;
  isSelf: boolean;
  isHider: boolean;
}

export function GameMap({ role, state }: GameMapProps) {
  const initialRegion = useMemo(() => regionFromBoundary(state.boundary), [state.boundary]);

  const hiders = useMemo(
    () => (role === 'hider' ? (state as HiderGameState).hiders : []),
    [role, state],
  );

  const players = useMemo(() => {
    const result: PlayerEntry[] = [];

    for (const s of state.seekers) {
      if (s.coordinates) {
        result.push({ player: s, isSelf: s.id === state.self_player_id, isHider: false });
      }
    }

    for (const h of hiders) {
      if (h.coordinates) {
        result.push({ player: h, isSelf: h.id === state.self_player_id, isHider: true });
      }
    }

    result.sort((a, b) => {
      if (a.isSelf !== b.isSelf) return a.isSelf ? 1 : -1;
      return a.player.name.localeCompare(b.player.name);
    });

    // Count co-located players and mark the topmost in each group
    const locCounts = new Map<string, number>();
    for (const entry of result) {
      const [lon, lat] = entry.player.coordinates!.coordinates;
      const key = `${lon.toFixed(4)},${lat.toFixed(4)}`;
      locCounts.set(key, (locCounts.get(key) ?? 0) + 1);
    }

    const locSeen = new Map<string, number>();
    const withStack = result.map((entry, index) => {
      const [lon, lat] = entry.player.coordinates!.coordinates;
      const key = `${lon.toFixed(4)},${lat.toFixed(4)}`;
      const seen = (locSeen.get(key) ?? 0) + 1;
      locSeen.set(key, seen);
      const total = locCounts.get(key)!;
      const isTopOfStack = seen === total;
      return { ...entry, index, stackCount: isTopOfStack && total > 1 ? total : 0 };
    });

    return withStack;
  }, [state.seekers, state.self_player_id, hiders]);

  return (
    <MapView style={{ flex: 1 }} initialRegion={initialRegion} onPress={() => {}}>
      <BoundaryOverlay boundary={state.boundary} />
      {state.routes.map((route) => (
        <TransitRoute key={route.id} route={route} stops={state.stops} />
      ))}
      {players.map(({ player, isSelf, isHider, index, stackCount }) => (
        <PlayerPin
          key={player.id}
          player={player}
          isSelf={isSelf}
          isHider={isHider}
          zIndex={index}
          stackCount={stackCount}
        />
      ))}
    </MapView>
  );
}
