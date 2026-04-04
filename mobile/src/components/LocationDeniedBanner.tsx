import { Linking, Pressable, StyleSheet, Text, View } from 'react-native';

export function LocationDeniedBanner() {
  return (
    <View style={styles.container}>
      <Text style={styles.text}>Location access denied</Text>
      <Pressable onPress={() => void Linking.openSettings()}>
        <Text style={styles.link}>Open Settings</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingVertical: 10,
    backgroundColor: '#E67E22',
  },
  text: {
    color: '#fff',
    fontSize: 14,
    fontWeight: '600',
  },
  link: {
    color: '#fff',
    fontSize: 14,
    fontWeight: '700',
    textDecorationLine: 'underline',
  },
});
