import { MaterialCommunityIcons } from '@expo/vector-icons';
import {
  Dimensions,
  Image,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';

import { authHeader } from '@/api/auth';
import { API_BASE_URL } from '@/api/client';
import { useGameplayStore } from '@/stores/gameplayStore';
import { photoSubjectLabel } from '@/utils/photoSubjects';

interface PhotoViewerModalProps {
  gameId: string;
}

function resolvePlayerName(playerId: string | null): string | null {
  if (!playerId) return null;
  const gameplay = useGameplayStore.getState();
  if (gameplay.status !== 'connected') return null;
  const fromHiders = gameplay.state.hiders.find((p) => p.id === playerId);
  if (fromHiders) return fromHiders.name;
  return gameplay.state.seekers.find((p) => p.id === playerId)?.name ?? null;
}

function formatTimestamp(iso: string | null): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (isNaN(d.getTime())) return null;
  return d.toLocaleString();
}

export function PhotoViewerModal({ gameId }: PhotoViewerModalProps) {
  const viewer = useGameplayStore((s) => s.photoViewer);
  const closePhotoViewer = useGameplayStore((s) => s.closePhotoViewer);

  if (!viewer) return null;

  const uri = `${API_BASE_URL}/games/${gameId}/questions/${viewer.questionId}/photo`;
  const { width, height } = Dimensions.get('window');
  const subjectText = photoSubjectLabel(viewer.subject);
  const submitterName = resolvePlayerName(viewer.submittedBy);
  const timestamp = formatTimestamp(viewer.submittedAt);
  const captionParts = [subjectText, submitterName, timestamp].filter(Boolean) as string[];
  const caption = captionParts.length > 0 ? captionParts.join(' · ') : null;

  return (
    <Modal
      visible
      animationType="fade"
      presentationStyle="fullScreen"
      onRequestClose={closePhotoViewer}
    >
      <View style={styles.backdrop}>
        <ScrollView
          maximumZoomScale={4}
          minimumZoomScale={1}
          pinchGestureEnabled
          contentContainerStyle={styles.center}
          centerContent
          showsHorizontalScrollIndicator={false}
          showsVerticalScrollIndicator={false}
        >
          <Image
            key={viewer.questionId}
            source={{ uri, headers: authHeader() }}
            style={{ width, height }}
            resizeMode="contain"
          />
        </ScrollView>
        <Pressable onPress={closePhotoViewer} style={styles.closeBtn} hitSlop={16}>
          <MaterialCommunityIcons name="chevron-down" size={32} color="#fff" />
        </Pressable>
        {caption && (
          <View style={styles.captionWrap} pointerEvents="none">
            <Text style={styles.caption} numberOfLines={2}>
              {caption}
            </Text>
          </View>
        )}
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: '#000',
  },
  center: {
    flexGrow: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  closeBtn: {
    position: 'absolute',
    top: 48,
    left: 16,
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: 'rgba(0, 0, 0, 0.5)',
    alignItems: 'center',
    justifyContent: 'center',
  },
  captionWrap: {
    position: 'absolute',
    bottom: 32,
    left: 16,
    right: 16,
    paddingHorizontal: 12,
    paddingVertical: 8,
    backgroundColor: 'rgba(0, 0, 0, 0.55)',
    borderRadius: 8,
  },
  caption: {
    color: '#fff',
    fontSize: 13,
    textAlign: 'center',
  },
});
