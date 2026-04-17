import React from 'react';
import { Polygon } from 'react-native-maps';

import type { GeoJSONGeometry, GeoJSONMultiPolygon, GeoJSONPolygon } from '@/types/gameplay';
import { multiPolygonToParts, polygonToCoords, polygonToHoles } from '@/utils/geo';

const FILL_COLOR = 'rgba(52, 152, 219, 0.15)';
const STROKE_COLOR = '#3498DB';
const STROKE_WIDTH = 1;
const Z_INDEX = 460;

interface SafeZoneOverlayProps {
  safeZone: GeoJSONGeometry | null;
}

export const SafeZoneOverlay = React.memo(function SafeZoneOverlay({
  safeZone,
}: SafeZoneOverlayProps) {
  if (!safeZone) return null;

  if (safeZone.type === 'Polygon') {
    const polygon = safeZone as unknown as GeoJSONPolygon;
    return (
      <Polygon
        coordinates={polygonToCoords(polygon)}
        holes={polygonToHoles(polygon)}
        fillColor={FILL_COLOR}
        strokeColor={STROKE_COLOR}
        strokeWidth={STROKE_WIDTH}
        zIndex={Z_INDEX}
      />
    );
  }

  if (safeZone.type === 'MultiPolygon') {
    const parts = multiPolygonToParts(safeZone as unknown as GeoJSONMultiPolygon);
    return (
      <>
        {parts.map((part, i) => (
          <Polygon
            key={i}
            coordinates={part.coordinates}
            holes={part.holes}
            fillColor={FILL_COLOR}
            strokeColor={STROKE_COLOR}
            strokeWidth={STROKE_WIDTH}
            zIndex={Z_INDEX}
          />
        ))}
      </>
    );
  }

  return null;
});
