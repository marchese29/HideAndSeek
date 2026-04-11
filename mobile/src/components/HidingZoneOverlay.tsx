import React from 'react';
import { Polygon } from 'react-native-maps';

import type { GeoJSONGeometry, GeoJSONMultiPolygon, GeoJSONPolygon } from '@/types/gameplay';
import { multiPolygonToParts, polygonToCoords, polygonToHoles } from '@/utils/geo';

const FILL_COLOR = 'rgba(52, 152, 219, 0.15)';
const STROKE_COLOR = '#3498DB';
const STROKE_WIDTH = 2;
const Z_INDEX = 450;

interface HidingZoneOverlayProps {
  hidingZone: GeoJSONGeometry | null;
}

export const HidingZoneOverlay = React.memo(function HidingZoneOverlay({
  hidingZone,
}: HidingZoneOverlayProps) {
  if (!hidingZone) return null;

  if (hidingZone.type === 'Polygon') {
    const polygon = hidingZone as unknown as GeoJSONPolygon;
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

  if (hidingZone.type === 'MultiPolygon') {
    const parts = multiPolygonToParts(hidingZone as unknown as GeoJSONMultiPolygon);
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
