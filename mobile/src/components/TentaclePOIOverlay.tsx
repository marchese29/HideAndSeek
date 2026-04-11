import React from 'react';
import { StyleSheet, View } from 'react-native';
import { Marker } from 'react-native-maps';

import type { TentaclePOIPreviewResponse } from '@/types/gameplay';
import { toLatLng } from '@/utils/geo';

const Z_INDEX = 1600;
const POI_COLOR = 'rgb(138, 92, 199)';
const DOT_SIZE = 10;

interface TentaclePOIOverlayProps {
  pois: TentaclePOIPreviewResponse[];
}

export const TentaclePOIOverlay = React.memo(function TentaclePOIOverlay({
  pois,
}: TentaclePOIOverlayProps) {
  if (pois.length === 0) return null;

  return (
    <>
      {pois.map((poi) => (
        <Marker
          key={poi.feature_id}
          coordinate={toLatLng(poi.location)}
          title={poi.name}
          anchor={{ x: 0.5, y: 0.5 }}
          zIndex={Z_INDEX}
          tracksViewChanges={false}
        >
          <View style={styles.dot} />
        </Marker>
      ))}
    </>
  );
});

const styles = StyleSheet.create({
  dot: {
    width: DOT_SIZE,
    height: DOT_SIZE,
    borderRadius: DOT_SIZE / 2,
    backgroundColor: POI_COLOR,
  },
});
