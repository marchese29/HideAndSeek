import { useEffect, useMemo, useRef, useState } from 'react';
import MapView from 'react-native-maps';

import { BoundaryOverlay } from '@/components/BoundaryOverlay';
import { CandidateStopOverlay } from '@/components/CandidateStopOverlay';
import { ExclusionOverlay } from '@/components/ExclusionOverlay';
import { HidingZoneOverlay } from '@/components/HidingZoneOverlay';
import { PlayerPin } from '@/components/PlayerPin';
import { PreviewBoundaryOverlay } from '@/components/PreviewBoundaryOverlay';
import { SafeZoneOverlay } from '@/components/SafeZoneOverlay';
import { TentaclePOIOverlay } from '@/components/TentaclePOIOverlay';
import { TransitRoute } from '@/components/TransitRoute';
import { useActiveQuestionBoundary } from '@/hooks/useActiveQuestionBoundary';
import { useHiderQuestionBoundary } from '@/hooks/useHiderQuestionBoundary';
import { useHidingZone } from '@/hooks/useHidingZone';
import { usePreviewBoundary } from '@/hooks/usePreviewBoundary';
import { useGameplayStore } from '@/stores/gameplayStore';
import type {
  GameInfo,
  GamePlayer,
  GeoJSONMultiPolygon,
  GeoJSONPolygon,
  HiderGameState,
  SeekerGameState,
  StopResponse,
} from '@/types/gameplay';
import { regionFromBoundary, regionFromPolygon } from '@/utils/geo';

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
  gameInfo: GameInfo;
  highlightedStopId?: string | null;
  onCandidateStopPress?: (stopId: string) => void;
  onMapPress?: () => void;
  endgameStationPicking?: boolean;
  endgameCandidateStations?: StopResponse[];
  endgameHighlightedStopId?: string | null;
  onEndgameCandidatePress?: (stopId: string) => void;
}

interface PlayerEntry {
  player: GamePlayer;
  isSelf: boolean;
  isHider: boolean;
}

export function GameMap({
  role,
  state,
  gameInfo,
  highlightedStopId,
  onCandidateStopPress,
  onMapPress,
  endgameStationPicking,
  endgameCandidateStations,
  endgameHighlightedStopId,
  onEndgameCandidatePress,
}: GameMapProps) {
  const mapRef = useRef<MapView>(null);
  const hasAnimatedToZone = useRef(false);
  const hasAnimatedToEndgame = useRef(false);
  const initialRegion = useMemo(() => regionFromBoundary(gameInfo.boundary), [gameInfo.boundary]);
  const selfLocation = useGameplayStore((s) => s.selfLocation);
  const endgameView = useGameplayStore((s) => s.endgameView);
  const {
    boundary: previewBoundary,
    questionType: previewQuestionType,
    tentaclePois,
  } = usePreviewBoundary();
  const { boundary: activeBoundary, questionType: activeQuestionType } =
    useActiveQuestionBoundary();
  const { boundary: hiderBoundary, questionType: hiderBoundaryType } = useHiderQuestionBoundary();

  // Elected station ID (post-election, permanent)
  const hiderStationId = role === 'hider' ? (state as HiderGameState).hider_station_id : null;

  // Hiding zone: preview (pre-election highlight) or permanent (post-election)
  // For seekers in endgame station picking, also show the highlighted station's zone
  const hiderZoneStationId = highlightedStopId ?? hiderStationId;
  const endgamePreviewStationId =
    endgameStationPicking && !endgameView ? (endgameHighlightedStopId ?? null) : null;
  const { hidingZone: hiderHidingZone } = useHidingZone(hiderZoneStationId);
  const { hidingZone: endgamePreviewZone } = useHidingZone(endgamePreviewStationId);

  // Proximity tier from hider state (drives amber zone color)
  const proximityTier = role === 'hider' ? (state as HiderGameState).proximity_tier : null;

  // Candidate stations from hider state
  const candidateStations = role === 'hider' ? (state as HiderGameState).candidate_stations : null;

  // Endgame candidate station IDs for overlay rendering
  const endgameCandidateIds = useMemo(
    () => (endgameCandidateStations ?? []).map((s) => s.id),
    [endgameCandidateStations],
  );

  // Hide candidate stops from TransitRoute so they don't fight for z-index
  const hiddenStopIds = useMemo(() => {
    const hiderIds = candidateStations ? new Set(candidateStations) : new Set<string>();
    if (endgameStationPicking && endgameCandidateStations) {
      for (const s of endgameCandidateStations) {
        hiderIds.add(s.id);
      }
    }
    return hiderIds.size > 0 ? hiderIds : undefined;
  }, [candidateStations, endgameStationPicking, endgameCandidateStations]);

  // Periodic tick forces the players memo to recompute staleness
  const [staleTick, setStaleTick] = useState(0);
  useEffect(() => {
    const interval = setInterval(() => setStaleTick((t) => t + 1), STALE_CHECK_INTERVAL_MS);
    return () => clearInterval(interval);
  }, []);

  // Animate camera to hiding zone centroid once after election
  useEffect(() => {
    if (!hiderStationId || !hiderHidingZone || hasAnimatedToZone.current) return;
    if (hiderHidingZone.type !== 'Polygon' && hiderHidingZone.type !== 'MultiPolygon') return;
    hasAnimatedToZone.current = true;
    const region = regionFromPolygon(
      hiderHidingZone as unknown as GeoJSONPolygon | GeoJSONMultiPolygon,
    );
    mapRef.current?.animateToRegion(region, 1000);
  }, [hiderStationId, hiderHidingZone]);

  // Animate camera to endgame hiding zone when endgame view activates
  useEffect(() => {
    if (!endgameView) {
      hasAnimatedToEndgame.current = false;
      return;
    }
    if (hasAnimatedToEndgame.current) return;
    const hz = endgameView.hidingZone;
    if (hz.type !== 'Polygon' && hz.type !== 'MultiPolygon') return;
    hasAnimatedToEndgame.current = true;
    const region = regionFromPolygon(hz as unknown as GeoJSONPolygon | GeoJSONMultiPolygon);
    mapRef.current?.animateToRegion(region, 1000);
  }, [endgameView]);

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

  // Determine which overlays to show based on endgame state
  const showEndgameOverlays = endgameView !== null;
  const showEndgameCandidates =
    endgameStationPicking && !showEndgameOverlays && endgameCandidateIds.length > 0;

  return (
    <MapView ref={mapRef} style={{ flex: 1 }} initialRegion={initialRegion} onPress={onMapPress}>
      <BoundaryOverlay boundary={gameInfo.boundary} />
      {gameInfo.routes.map((route) => (
        <TransitRoute
          key={route.id}
          route={route}
          stops={gameInfo.stops}
          hiddenStopIds={hiddenStopIds}
        />
      ))}
      {candidateStations && candidateStations.length > 0 && onCandidateStopPress && (
        <CandidateStopOverlay
          candidateStationIds={candidateStations}
          stops={gameInfo.stops}
          highlightedStopId={highlightedStopId ?? null}
          onStopPress={onCandidateStopPress}
        />
      )}
      {/* Endgame candidate stations (seeker station picking) */}
      {showEndgameCandidates && onEndgameCandidatePress && (
        <CandidateStopOverlay
          candidateStationIds={endgameCandidateIds}
          stops={endgameCandidateStations ?? []}
          highlightedStopId={endgameHighlightedStopId ?? null}
          onStopPress={onEndgameCandidatePress}
        />
      )}
      {/* Endgame station picking: show hiding zone preview for highlighted station */}
      {showEndgameCandidates && <HidingZoneOverlay hidingZone={endgamePreviewZone} />}
      {/* Endgame active: stroke-only hiding zone + safe zone + endgame exclusion */}
      {showEndgameOverlays && (
        <>
          <HidingZoneOverlay hidingZone={endgameView.hidingZone} strokeOnly />
          <SafeZoneOverlay safeZone={endgameView.safeZone} />
          <ExclusionOverlay exclusion={endgameView.totalExclusion} />
        </>
      )}
      {/* Normal hiding zone (hider or seeker not in endgame) */}
      {!showEndgameOverlays && !showEndgameCandidates && (
        <HidingZoneOverlay
          hidingZone={hiderHidingZone}
          proximityEntered={proximityTier === 'entered'}
        />
      )}
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
      {/* Long-game exclusion (invisible during endgame view — kept mounted to avoid Apple Maps ghost polygon) */}
      {role === 'seeker' && state.phase === 'seeking' && (
        <ExclusionOverlay
          exclusion={(state as SeekerGameState).total_exclusion}
          visible={!showEndgameOverlays}
        />
      )}
      {role === 'seeker' && (
        <PreviewBoundaryOverlay
          boundary={activeBoundary}
          questionType={activeQuestionType}
          variant="active"
        />
      )}
      {role === 'seeker' && (
        <PreviewBoundaryOverlay boundary={previewBoundary} questionType={previewQuestionType} />
      )}
      {role === 'seeker' && tentaclePois && tentaclePois.length > 0 && (
        <TentaclePOIOverlay pois={tentaclePois} />
      )}
      {role === 'hider' && (
        <PreviewBoundaryOverlay
          boundary={hiderBoundary}
          questionType={hiderBoundaryType}
          variant="active"
        />
      )}
    </MapView>
  );
}
