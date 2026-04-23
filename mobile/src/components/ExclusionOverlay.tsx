import React from 'react';
import { Polygon } from 'react-native-maps';

import type { GeoJSONGeometry, GeoJSONMultiPolygon, GeoJSONPolygon } from '@/types/gameplay';
import { multiPolygonToParts, polygonToCoords, polygonToHoles } from '@/utils/geo';

const DEFAULT_FILL_COLOR = 'rgba(231, 76, 60, 0.25)';
const DEFAULT_STROKE_COLOR = 'rgba(231, 76, 60, 0.5)';
const DEFAULT_STROKE_WIDTH = 1;
const DEFAULT_Z_INDEX = 2000;

interface ExclusionOverlayProps {
  exclusion: GeoJSONGeometry | null;
  /** When false, polygon stays mounted but renders fully transparent (Apple Maps workaround). */
  visible?: boolean;
  fillColor?: string;
  strokeColor?: string;
  strokeWidth?: number;
  zIndex?: number;
}

export const ExclusionOverlay = React.memo(function ExclusionOverlay({
  exclusion,
  visible = true,
  fillColor: fillColorProp = DEFAULT_FILL_COLOR,
  strokeColor: strokeColorProp = DEFAULT_STROKE_COLOR,
  strokeWidth = DEFAULT_STROKE_WIDTH,
  zIndex = DEFAULT_Z_INDEX,
}: ExclusionOverlayProps) {
  if (!exclusion) return null;

  const fillColor = visible ? fillColorProp : 'transparent';
  const strokeColor = visible ? strokeColorProp : 'transparent';

  if (exclusion.type === 'Polygon') {
    const polygon = exclusion as unknown as GeoJSONPolygon;
    return (
      <Polygon
        coordinates={polygonToCoords(polygon)}
        holes={polygonToHoles(polygon)}
        fillColor={fillColor}
        strokeColor={strokeColor}
        strokeWidth={strokeWidth}
        zIndex={zIndex}
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
            fillColor={fillColor}
            strokeColor={strokeColor}
            strokeWidth={strokeWidth}
            zIndex={zIndex}
          />
        ))}
      </>
    );
  }

  return null;
});
