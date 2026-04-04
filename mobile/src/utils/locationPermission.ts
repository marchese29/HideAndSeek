import * as Location from 'expo-location';

/**
 * Checks foreground location permission and requests it if not yet granted.
 * Returns true when permission is granted, false otherwise.
 *
 * Call this imperatively (not as a hook) from create/join handlers so the OS
 * prompt appears early — before the player enters the game.
 */
export async function requestLocationPermission(): Promise<boolean> {
  const { status: existing } = await Location.getForegroundPermissionsAsync();
  if (existing === 'granted') return true;

  const { status } = await Location.requestForegroundPermissionsAsync();
  return status === 'granted';
}
