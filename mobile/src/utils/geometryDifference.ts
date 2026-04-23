import { difference } from '@turf/difference';
import { feature, featureCollection } from '@turf/helpers';
import type { MultiPolygon, Polygon } from 'geojson';

import type { GeoJSONGeometry, GeoJSONMultiPolygon, GeoJSONPolygon } from '@/types/gameplay';

/**
 * Subtract `subtrahend` from `minuend`, returning the part of `minuend` that
 * falls outside `subtrahend`. Used by the seeker question history scrubber to
 * render each question's marginal exclusion without it double-rendering over
 * already-excluded cumulative area.
 *
 * Only Polygon / MultiPolygon inputs are meaningful — other geometry types
 * pass through as the minuend.
 */
export function geometryDifference(
  minuend: GeoJSONGeometry | null,
  subtrahend: GeoJSONGeometry | null,
): GeoJSONGeometry | null {
  if (!minuend) return null;
  if (!subtrahend) return minuend;
  if (!isPolygonal(minuend) || !isPolygonal(subtrahend)) return minuend;

  const minFeature = feature(minuend as Polygon | MultiPolygon);
  const subFeature = feature(subtrahend as Polygon | MultiPolygon);
  const result = difference(featureCollection([minFeature, subFeature]));
  return result ? (result.geometry as GeoJSONGeometry) : null;
}

function isPolygonal(g: GeoJSONGeometry): g is GeoJSONPolygon | GeoJSONMultiPolygon {
  return g.type === 'Polygon' || g.type === 'MultiPolygon';
}
