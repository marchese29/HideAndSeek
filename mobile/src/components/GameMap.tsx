import { useEffect, useMemo, useState } from 'react';
import MapView from 'react-native-maps';

import { BoundaryOverlay } from '@/components/BoundaryOverlay';
import { ExclusionOverlay } from '@/components/ExclusionOverlay';
import { PlayerPin } from '@/components/PlayerPin';
import { TransitRoute } from '@/components/TransitRoute';
import { useGameplayStore } from '@/stores/gameplayStore';
import type { GamePlayer, HiderGameState, SeekerGameState } from '@/types/gameplay';
import { regionFromBoundary } from '@/utils/geo';

const STALE_THRESHOLD_MS = 60_000;
const STALE_CHECK_INTERVAL_MS = 10_000;

function isTimestampStale(timestamp: string | null): boolean {
  if (!timestamp) return false;
  // Server timestamps may omit the timezone — treat as UTC
  const utc = timestamp.endsWith('Z') || timestamp.includes('+') ? timestamp : timestamp + 'Z';
  return Date.now() - new Date(utc).getTime() > STALE_THRESHOLD_MS;
}

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
  const selfLocation = useGameplayStore((s) => s.selfLocation);

  // Periodic tick forces the players memo to recompute staleness
  const [staleTick, setStaleTick] = useState(0);
  useEffect(() => {
    const interval = setInterval(() => setStaleTick((t) => t + 1), STALE_CHECK_INTERVAL_MS);
    return () => clearInterval(interval);
  }, []);

  const hiders = useMemo(
    () => (role === 'hider' ? (state as HiderGameState).hiders : []),
    [role, state],
  );

  const players = useMemo(() => {
    const result: PlayerEntry[] = [];

    /** Apply optimistic selfLocation override when available. */
    function withSelfOverride(p: GamePlayer): GamePlayer {
      if (p.id !== state.self_player_id || !selfLocation) return p;
      return { ...p, coordinates: selfLocation.coordinates, timestamp: selfLocation.timestamp };
    }

    for (const s of state.seekers) {
      const effective = withSelfOverride(s);
      if (effective.coordinates) {
        result.push({ player: effective, isSelf: s.id === state.self_player_id, isHider: false });
      }
    }

    for (const h of hiders) {
      const effective = withSelfOverride(h);
      if (effective.coordinates) {
        result.push({ player: effective, isSelf: h.id === state.self_player_id, isHider: true });
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
      const isStale = isTimestampStale(entry.player.timestamp);
      return { ...entry, index, stackCount: isTopOfStack && total > 1 ? total : 0, isStale };
    });

    return withStack;
    // eslint-disable-next-line react-hooks/exhaustive-deps -- staleTick forces periodic staleness recheck
  }, [state.seekers, state.self_player_id, hiders, selfLocation, staleTick]);

  return (
    <MapView style={{ flex: 1 }} initialRegion={initialRegion} onPress={() => {}}>
      <BoundaryOverlay boundary={state.boundary} />
      {state.routes.map((route) => (
        <TransitRoute key={route.id} route={route} stops={state.stops} />
      ))}
      {players.map(({ player, isSelf, isHider, isStale, index, stackCount }) => (
        <PlayerPin
          key={player.id}
          player={player}
          isSelf={isSelf}
          isHider={isHider}
          isStale={isStale}
          zIndex={1000 + index}
          stackCount={stackCount}
        />
      ))}
      {role === 'seeker' && state.phase === 'seeking' && (
        <ExclusionOverlay exclusion={(state as SeekerGameState).total_exclusion} />
      )}
    </MapView>
  );
}
