import { MaterialCommunityIcons } from '@expo/vector-icons';
import { FlatList, Modal, Pressable, StyleSheet, Text, View } from 'react-native';

import type { SeekerQuestionHistoryEntry } from '@/types/gameplay';

import { QuestionHistoryRow, questionHistoryRowStyles } from './QuestionHistoryRow';

interface QuestionCutoffModalProps {
  visible: boolean;
  onClose: () => void;
  onSelect: (afterQuestion: number) => void;
  questions: SeekerQuestionHistoryEntry[];
  convention: string;
}

export function QuestionCutoffModal({
  visible,
  onClose,
  onSelect,
  questions,
  convention,
}: QuestionCutoffModalProps) {
  const answered = questions.filter((q) => q.status === 'answered');
  const unit = convention === 'metric' ? 'km' : 'mi';

  const maxSequence = answered.length > 0 ? Math.max(...answered.map((q) => q.sequence)) : 0;

  return (
    <Modal
      visible={visible}
      animationType="slide"
      presentationStyle="pageSheet"
      onRequestClose={onClose}
    >
      <View style={styles.container}>
        <View style={styles.header}>
          <Text style={styles.title}>Start Endgame With</Text>
          <Pressable style={styles.closeButton} onPress={onClose}>
            <MaterialCommunityIcons name="close" size={22} color="rgba(255,255,255,0.6)" />
          </Pressable>
        </View>

        <FlatList
          data={answered}
          keyExtractor={(item) => item.question_id}
          contentContainerStyle={styles.list}
          renderItem={({ item }) => (
            <QuestionHistoryRow
              entry={item}
              unit={unit}
              onPress={() => {
                onSelect(item.sequence - 1);
                onClose();
              }}
            />
          )}
          ListFooterComponent={
            <Pressable
              style={({ pressed }) => [
                questionHistoryRowStyles.row,
                styles.noneRow,
                pressed && questionHistoryRowStyles.rowPressed,
              ]}
              onPress={() => {
                onSelect(maxSequence);
                onClose();
              }}
            >
              <View style={[questionHistoryRowStyles.iconCircle, { backgroundColor: '#555' }]}>
                <MaterialCommunityIcons name="cancel" size={18} color="#fff" />
              </View>
              <Text style={styles.noneLabel}>None</Text>
              <Text style={styles.noneHint}>Full zone, no exclusions</Text>
            </Pressable>
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
  },
  noneRow: {
    marginTop: 8,
    borderBottomWidth: 0,
  },
  noneLabel: {
    fontSize: 15,
    fontWeight: '500',
    color: 'rgba(255,255,255,0.5)',
    marginLeft: 12,
    flex: 1,
  },
  noneHint: {
    fontSize: 13,
    color: 'rgba(255,255,255,0.3)',
  },
});
