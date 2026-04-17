import React from 'react';
import { Polygon } from 'react-native-maps';

import type { GeoJSONGeometry, GeoJSONMultiPolygon, GeoJSONPolygon } from '@/types/gameplay';
import { multiPolygonToParts, polygonToCoords, polygonToHoles } from '@/utils/geo';

const BLUE_FILL = 'rgba(52, 152, 219, 0.15)';
const BLUE_STROKE = '#3498DB';
const AMBER_FILL = 'rgba(245, 158, 11, 0.15)';
const AMBER_STROKE = '#F59E0B';
const STROKE_WIDTH = 2;
const Z_INDEX = 450;

interface HidingZoneOverlayProps {
  hidingZone: GeoJSONGeometry | null;
  proximityEntered?: boolean;
  strokeOnly?: boolean;
}

export const HidingZoneOverlay = React.memo(function HidingZoneOverlay({
  hidingZone,
  proximityEntered,
  strokeOnly,
}: HidingZoneOverlayProps) {
  if (!hidingZone) return null;

  const fillColor = strokeOnly ? 'transparent' : proximityEntered ? AMBER_FILL : BLUE_FILL;
  const strokeColor = proximityEntered ? AMBER_STROKE : BLUE_STROKE;

  if (hidingZone.type === 'Polygon') {
    const polygon = hidingZone as unknown as GeoJSONPolygon;
    return (
      <Polygon
        coordinates={polygonToCoords(polygon)}
        holes={polygonToHoles(polygon)}
        fillColor={fillColor}
        strokeColor={strokeColor}
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
            fillColor={fillColor}
            strokeColor={strokeColor}
            strokeWidth={STROKE_WIDTH}
            zIndex={Z_INDEX}
          />
        ))}
      </>
    );
  }

  return null;
});
