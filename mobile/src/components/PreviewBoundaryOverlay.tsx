import React, { useMemo } from 'react';
import { Polyline } from 'react-native-maps';

import { getTypeColors } from '@/constants/questionColors';
import type { GeoJSONGeometry, GeoJSONLineString, GeoJSONMultiLineString } from '@/types/gameplay';
import { shapeToCoordArrays } from '@/utils/geo';

const FALLBACK_RGB: [number, number, number] = [52, 152, 219];

const VARIANT_STYLES = {
  active: { alpha: 1, strokeWidth: 3, zIndex: 1550 },
  browse: { alpha: 0.7, strokeWidth: 3, zIndex: 1500 },
} as const;

interface PreviewBoundaryOverlayProps {
  boundary: GeoJSONGeometry | null;
  questionType: string | null;
  variant?: 'active' | 'browse';
}

export const PreviewBoundaryOverlay = React.memo(function PreviewBoundaryOverlay({
  boundary,
  questionType,
  variant = 'browse',
}: PreviewBoundaryOverlayProps) {
  const segments = useMemo(() => {
    if (!boundary) return null;
    if (boundary.type !== 'LineString' && boundary.type !== 'MultiLineString') return null;
    return shapeToCoordArrays(boundary as unknown as GeoJSONLineString | GeoJSONMultiLineString);
  }, [boundary]);

  if (!segments) return null;

  const [r, g, b] = questionType ? getTypeColors(questionType).rgb : FALLBACK_RGB;
  const { alpha, strokeWidth, zIndex } = VARIANT_STYLES[variant];
  const strokeColor = `rgba(${r}, ${g}, ${b}, ${alpha})`;

  return (
    <>
      {segments.map((coords, i) => (
        <Polyline
          key={i}
          coordinates={coords}
          strokeColor={strokeColor}
          strokeWidth={strokeWidth}
          zIndex={zIndex}
        />
      ))}
    </>
  );
});
