import React, { useMemo } from 'react';
import { StyleSheet, View } from 'react-native';
import { Marker, Polyline } from 'react-native-maps';

import type { RouteResponse, StopResponse } from '@/types/gameplay';
import { shapeToCoordArrays, toLatLng } from '@/utils/geo';

interface TransitRouteProps {
  route: RouteResponse;
  stops: StopResponse[];
  /** Stop IDs to skip rendering (candidate stops rendered separately). */
  hiddenStopIds?: Set<string>;
}

export const TransitRoute = React.memo(function TransitRoute({
  route,
  stops,
  hiddenStopIds,
}: TransitRouteProps) {
  const segments = useMemo(() => shapeToCoordArrays(route.shape), [route.shape]);

  const routeStops = useMemo(() => {
    const stopMap = new Map(stops.map((s) => [s.id, s]));
    const seen = new Set<string>();
    const result: StopResponse[] = [];
    for (const id of route.stop_ids) {
      if (seen.has(id)) continue;
      seen.add(id);
      if (hiddenStopIds?.has(id)) continue;
      const stop = stopMap.get(id);
      if (stop) result.push(stop);
    }
    return result;
  }, [stops, route.stop_ids, hiddenStopIds]);

  return (
    <>
      {segments.map((coords, i) => (
        <Polyline
          key={`${route.id}-line-${i}`}
          coordinates={coords}
          strokeColor={`#${route.color}`}
          strokeWidth={3}
        />
      ))}
      {routeStops.map((stop) => (
        <Marker
          key={`${route.id}-${stop.id}`}
          coordinate={toLatLng(stop.coordinates)}
          tracksViewChanges={false}
          tappable={false}
          anchor={{ x: 0.5, y: 0.5 }}
        >
          <View style={styles.dot} />
        </Marker>
      ))}
    </>
  );
});

const styles = StyleSheet.create({
  dot: {
    width: 5,
    height: 5,
    borderRadius: 2,
    backgroundColor: '#FFFFFF',
    borderWidth: 1,
    borderColor: 'rgba(0, 0, 0, 0.3)',
  },
});
