import { StyleSheet, Text, View } from 'react-native';

export function PlaceholderScreen() {
  return (
    <View style={styles.container}>
      <Text style={styles.text}>Coming soon</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  text: {
    fontSize: 16,
    color: 'rgba(255, 255, 255, 0.4)',
  },
});
