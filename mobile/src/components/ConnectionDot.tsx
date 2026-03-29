import { StyleSheet, View } from 'react-native';

interface ConnectionDotProps {
  connected: boolean;
}

/** Small status dot: green when the SSE connection is live, red when disconnected. */
export function ConnectionDot({ connected }: ConnectionDotProps) {
  return <View style={[styles.dot, connected ? styles.connected : styles.disconnected]} />;
}

const styles = StyleSheet.create({
  dot: {
    position: 'absolute',
    top: 10,
    right: 10,
    width: 10,
    height: 10,
    borderRadius: 5,
  },
  connected: {
    backgroundColor: '#2ECC71',
  },
  disconnected: {
    backgroundColor: '#E74C3C',
  },
});
