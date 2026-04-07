import type { Region } from 'react-native-maps';

import type {
  GeoJSONLineString,
  GeoJSONMultiLineString,
  GeoJSONMultiPolygon,
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

/** Extract inner rings (holes) from a GeoJSON Polygon as arrays of LatLng. */
export function polygonToHoles(polygon: GeoJSONPolygon): LatLng[][] {
  return polygon.coordinates
    .slice(1)
    .map((ring) => ring.map((pair) => ({ latitude: pair[1], longitude: pair[0] })));
}

/** Convert a GeoJSON MultiPolygon to per-polygon parts with outer ring + holes. */
export function multiPolygonToParts(
  multi: GeoJSONMultiPolygon,
): { coordinates: LatLng[]; holes: LatLng[][] }[] {
  return multi.coordinates.map((polyCoords) => ({
    coordinates: polyCoords[0].map((pair) => ({ latitude: pair[1], longitude: pair[0] })),
    holes: polyCoords
      .slice(1)
      .map((ring) => ring.map((pair) => ({ latitude: pair[1], longitude: pair[0] }))),
  }));
}

/** Haversine distance between two GeoJSON Points, in meters. */
export function haversineMeters(a: GeoJSONPoint, b: GeoJSONPoint): number {
  const R = 6_371_000;
  const [lonA, latA] = a.coordinates;
  const [lonB, latB] = b.coordinates;
  const dLat = ((latB - latA) * Math.PI) / 180;
  const dLon = ((lonB - lonA) * Math.PI) / 180;
  const sinHalfLat = Math.sin(dLat / 2);
  const sinHalfLon = Math.sin(dLon / 2);
  const h =
    sinHalfLat * sinHalfLat +
    Math.cos((latA * Math.PI) / 180) * Math.cos((latB * Math.PI) / 180) * sinHalfLon * sinHalfLon;
  return 2 * R * Math.asin(Math.sqrt(h));
}

/** Convert meters to convention units (km or mi). */
export function metersToConvention(meters: number, convention: string): number {
  return convention === 'metric' ? meters / 1000 : meters / 1609.344;
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
