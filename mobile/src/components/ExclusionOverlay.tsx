import React from 'react';
import { Polygon } from 'react-native-maps';

import type { GeoJSONGeometry, GeoJSONMultiPolygon, GeoJSONPolygon } from '@/types/gameplay';
import { multiPolygonToParts, polygonToCoords, polygonToHoles } from '@/utils/geo';

const FILL_COLOR = 'rgba(231, 76, 60, 0.25)';
const STROKE_COLOR = 'rgba(231, 76, 60, 0.5)';
const STROKE_WIDTH = 1;
const Z_INDEX = 2000;

interface ExclusionOverlayProps {
  exclusion: GeoJSONGeometry | null;
}

export const ExclusionOverlay = React.memo(function ExclusionOverlay({
  exclusion,
}: ExclusionOverlayProps) {
  if (!exclusion) return null;

  if (exclusion.type === 'Polygon') {
    const polygon = exclusion as unknown as GeoJSONPolygon;
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

  if (exclusion.type === 'MultiPolygon') {
    const parts = multiPolygonToParts(exclusion as unknown as GeoJSONMultiPolygon);
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
