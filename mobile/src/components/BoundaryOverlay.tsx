import React from 'react';
import { Polygon } from 'react-native-maps';

import type { GeoJSONPolygon } from '@/types/gameplay';
import { polygonToCoords } from '@/utils/geo';

interface BoundaryOverlayProps {
  boundary: GeoJSONPolygon;
}

export const BoundaryOverlay = React.memo(function BoundaryOverlay({
  boundary,
}: BoundaryOverlayProps) {
  return (
    <Polygon
      coordinates={polygonToCoords(boundary)}
      strokeColor="rgba(44, 62, 80, 0.6)"
      strokeWidth={2}
      fillColor="transparent"
    />
  );
});
