import React from 'react';
import { Polygon } from 'react-native-maps';

import type { GeoJSONMultiPolygon } from '@/types/gameplay';
import { multiPolygonToParts } from '@/utils/geo';

interface BoundaryOverlayProps {
  boundary: GeoJSONMultiPolygon;
}

export const BoundaryOverlay = React.memo(function BoundaryOverlay({
  boundary,
}: BoundaryOverlayProps) {
  const parts = multiPolygonToParts(boundary);
  return (
    <>
      {parts.map((part, i) => (
        <Polygon
          key={i}
          coordinates={part.coordinates}
          strokeColor="rgba(44, 62, 80, 0.6)"
          strokeWidth={2}
          fillColor="transparent"
        />
      ))}
    </>
  );
});
