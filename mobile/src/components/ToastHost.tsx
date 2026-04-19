import { useEffect, useMemo, useRef } from 'react';
import { Animated, PanResponder, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { type Toast, useToastStore } from '@/stores/toastStore';

const ENTER_MS = 250;
const EXIT_MS = 200;
const HOLD_MS = 5000;
const HIDDEN_Y = -120;
const SWIPE_DISMISS_THRESHOLD = 30;
const TAP_THRESHOLD = 10;

const SEVERITY_BG: Record<Toast['severity'], string> = {
  warning: '#E74C3C',
  info: '#2C3E50',
};

export function ToastHost() {
  const current = useToastStore((s) => s.current);
  const dismiss = useToastStore((s) => s.dismiss);
  const insets = useSafeAreaInsets();

  const translateY = useRef(new Animated.Value(HIDDEN_Y)).current;
  const opacity = useRef(new Animated.Value(0)).current;
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const dismissingRef = useRef(false);
  const currentIdRef = useRef<string | null>(null);

  const beginExit = (id: string) => {
    if (dismissingRef.current) return;
    dismissingRef.current = true;
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    Animated.parallel([
      Animated.timing(translateY, { toValue: HIDDEN_Y, duration: EXIT_MS, useNativeDriver: true }),
      Animated.timing(opacity, { toValue: 0, duration: EXIT_MS, useNativeDriver: true }),
    ]).start(() => {
      dismiss(id);
    });
  };

  useEffect(() => {
    const id = current?.id ?? null;
    if (id === currentIdRef.current) return;
    currentIdRef.current = id;

    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }

    if (!current) {
      dismissingRef.current = false;
      translateY.setValue(HIDDEN_Y);
      opacity.setValue(0);
      return;
    }

    dismissingRef.current = false;
    translateY.setValue(HIDDEN_Y);
    opacity.setValue(0);

    Animated.parallel([
      Animated.timing(translateY, { toValue: 0, duration: ENTER_MS, useNativeDriver: true }),
      Animated.timing(opacity, { toValue: 1, duration: ENTER_MS, useNativeDriver: true }),
    ]).start();

    const toastId = current.id;
    timerRef.current = setTimeout(() => beginExit(toastId), HOLD_MS);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current?.id]);

  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
      translateY.stopAnimation();
      opacity.stopAnimation();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const panResponder = useMemo(
    () =>
      PanResponder.create({
        onStartShouldSetPanResponder: () => true,
        onMoveShouldSetPanResponder: () => true,
        onPanResponderMove: (_evt, gesture) => {
          if (gesture.dy < 0) translateY.setValue(gesture.dy);
        },
        onPanResponderRelease: (_evt, gesture) => {
          const id = currentIdRef.current;
          if (!id) return;
          if (gesture.dy < -SWIPE_DISMISS_THRESHOLD) {
            beginExit(id);
          } else if (Math.abs(gesture.dx) < TAP_THRESHOLD && Math.abs(gesture.dy) < TAP_THRESHOLD) {
            beginExit(id);
          } else {
            Animated.spring(translateY, { toValue: 0, useNativeDriver: true }).start();
          }
        },
        onPanResponderTerminate: () => {
          Animated.spring(translateY, { toValue: 0, useNativeDriver: true }).start();
        },
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  if (!current) return null;

  return (
    <View pointerEvents="box-none" style={[styles.wrapper, { top: insets.top + 8 }]}>
      <Animated.View
        accessibilityLiveRegion="polite"
        accessibilityRole="alert"
        style={[
          styles.banner,
          {
            backgroundColor: SEVERITY_BG[current.severity],
            opacity,
            transform: [{ translateY }],
          },
        ]}
        {...panResponder.panHandlers}
      >
        <Text style={styles.text}>{current.message}</Text>
      </Animated.View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrapper: {
    position: 'absolute',
    left: 0,
    right: 0,
    zIndex: 100,
    alignItems: 'center',
    paddingHorizontal: 16,
  },
  banner: {
    width: '100%',
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderRadius: 10,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.25,
    shadowRadius: 4,
    elevation: 4,
  },
  text: {
    color: '#fff',
    fontSize: 14,
    fontWeight: '600',
    textAlign: 'center',
  },
});
