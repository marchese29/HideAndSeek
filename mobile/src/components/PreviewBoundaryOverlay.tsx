import React, { useMemo } from 'react';
import { Polyline } from 'react-native-maps';

import type { GeoJSONGeometry, GeoJSONLineString, GeoJSONMultiLineString } from '@/types/gameplay';
import { shapeToCoordArrays } from '@/utils/geo';

const TYPE_STROKE_COLORS: Record<string, string> = {
  radar: 'rgb(245, 121, 59)',
  thermometer: 'rgb(255, 191, 65)',
  matching: 'rgb(33, 47, 64)',
  measuring: 'rgb(77, 162, 100)',
  tentacles: 'rgb(138, 92, 199)',
};
const FALLBACK_STROKE_COLOR = 'rgb(52, 152, 219)';
const STROKE_WIDTH = 1.5;
const Z_INDEX = 1500;

interface PreviewBoundaryOverlayProps {
  boundary: GeoJSONGeometry | null;
  questionType: string | null;
}

export const PreviewBoundaryOverlay = React.memo(function PreviewBoundaryOverlay({
  boundary,
  questionType,
}: PreviewBoundaryOverlayProps) {
  const segments = useMemo(() => {
    if (!boundary) return null;
    if (boundary.type !== 'LineString' && boundary.type !== 'MultiLineString') return null;
    return shapeToCoordArrays(boundary as unknown as GeoJSONLineString | GeoJSONMultiLineString);
  }, [boundary]);

  if (!segments) return null;

  const strokeColor = (questionType && TYPE_STROKE_COLORS[questionType]) || FALLBACK_STROKE_COLOR;

  return (
    <>
      {segments.map((coords, i) => (
        <Polyline
          key={i}
          coordinates={coords}
          strokeColor={strokeColor}
          strokeWidth={STROKE_WIDTH}
          zIndex={Z_INDEX}
        />
      ))}
    </>
  );
});
