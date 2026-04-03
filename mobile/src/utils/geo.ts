import type { Region } from 'react-native-maps';

import type {
  GeoJSONLineString,
  GeoJSONMultiLineString,
  GeoJSONPoint,
  GeoJSONPolygon,
} from '@/types/gameplay';

export interface LatLng {
  latitude: number;
  longitude: number;
}

/** Convert a GeoJSON Point ([lon, lat]) to a react-native-maps LatLng. */
export function toLatLng(point: GeoJSONPoint): LatLng {
  return { latitude: point.coordinates[1], longitude: point.coordinates[0] };
}

/** Convert a GeoJSON LineString or MultiLineString to arrays of LatLng (one per segment). */
export function shapeToCoordArrays(shape: GeoJSONLineString | GeoJSONMultiLineString): LatLng[][] {
  const lines = shape.type === 'MultiLineString' ? shape.coordinates : [shape.coordinates];
  return lines.map((coords) =>
    coords.map((pair) => ({
      latitude: pair[1],
      longitude: pair[0],
    })),
  );
}

/** Convert a GeoJSON Polygon's outer ring to an array of LatLng. */
export function polygonToCoords(polygon: GeoJSONPolygon): LatLng[] {
  return polygon.coordinates[0].map((pair) => ({
    latitude: pair[1],
    longitude: pair[0],
  }));
}

/** Compute an initialRegion that fits the boundary with 10% padding. */
export function regionFromBoundary(polygon: GeoJSONPolygon): Region {
  const ring = polygon.coordinates[0];
  let minLat = Infinity;
  let maxLat = -Infinity;
  let minLon = Infinity;
  let maxLon = -Infinity;

  for (const pair of ring) {
    const lon = pair[0];
    const lat = pair[1];
    if (lat < minLat) minLat = lat;
    if (lat > maxLat) maxLat = lat;
    if (lon < minLon) minLon = lon;
    if (lon > maxLon) maxLon = lon;
  }

  return {
    latitude: (minLat + maxLat) / 2,
    longitude: (minLon + maxLon) / 2,
    latitudeDelta: (maxLat - minLat) * 1.1,
    longitudeDelta: (maxLon - minLon) * 1.1,
  };
}
