import { MaterialCommunityIcons } from '@expo/vector-icons';
import { useRef } from 'react';
import { FlatList, Modal, Pressable, StyleSheet, Text, View } from 'react-native';

import { type PhotoViewerState, useGameplayStore } from '@/stores/gameplayStore';
import type { HiderQuestionHistoryEntry } from '@/types/gameplay';

import { QuestionHistoryRow } from './QuestionHistoryRow';

interface HiderQuestionHistoryModalProps {
  visible: boolean;
  onClose: () => void;
  questions: HiderQuestionHistoryEntry[];
  convention: string;
  gameId: string;
}

export function HiderQuestionHistoryModal({
  visible,
  onClose,
  questions,
  convention,
  gameId,
}: HiderQuestionHistoryModalProps) {
  const unit = convention === 'metric' ? 'km' : 'mi';
  const pendingPhotoViewerRef = useRef<PhotoViewerState | null>(null);

  const handleDismiss = () => {
    onClose();
    const pending = pendingPhotoViewerRef.current;
    if (pending) {
      pendingPhotoViewerRef.current = null;
      useGameplayStore.getState().openPhotoViewer(pending);
    }
  };

  return (
    <Modal
      visible={visible}
      animationType="slide"
      presentationStyle="pageSheet"
      onRequestClose={onClose}
      onDismiss={handleDismiss}
    >
      <View style={styles.container}>
        <View style={styles.header}>
          <Text style={styles.title}>Question History</Text>
          <Pressable style={styles.closeButton} onPress={onClose}>
            <MaterialCommunityIcons name="close" size={22} color="rgba(255,255,255,0.6)" />
          </Pressable>
        </View>

        <FlatList
          data={questions}
          keyExtractor={(item) => item.question_id}
          contentContainerStyle={styles.list}
          renderItem={({ item }) => (
            <QuestionHistoryRow
              entry={item}
              unit={unit}
              gameId={gameId}
              onPhotoTap={(params) => {
                pendingPhotoViewerRef.current = {
                  questionId: params.questionId,
                  subject: params.subject,
                  submittedBy: params.submittedBy,
                  submittedAt: params.submittedAt,
                };
                onClose();
              }}
            />
          )}
          ListEmptyComponent={
            <View style={styles.emptyContainer}>
              <Text style={styles.emptyText}>No questions answered yet.</Text>
            </View>
          }
        />
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#1C1C1E',
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingTop: 16,
    paddingBottom: 12,
  },
  title: {
    fontSize: 18,
    fontWeight: '600',
    color: '#fff',
  },
  closeButton: {
    padding: 4,
  },
  list: {
    paddingHorizontal: 16,
    paddingBottom: 40,
    flexGrow: 1,
  },
  emptyContainer: {
    flex: 1,
    alignItems: 'center',
    paddingTop: 40,
  },
  emptyText: {
    fontSize: 15,
    color: 'rgba(255,255,255,0.4)',
    textAlign: 'center',
  },
});
