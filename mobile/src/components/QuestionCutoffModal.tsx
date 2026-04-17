import { MaterialCommunityIcons } from '@expo/vector-icons';
import { FlatList, Modal, Pressable, StyleSheet, Text, View } from 'react-native';

import { getTypeColors } from '@/constants/questionColors';
import type { SeekerQuestionHistoryEntry } from '@/types/gameplay';

const QUESTION_TYPE_ICONS: Record<string, keyof typeof MaterialCommunityIcons.glyphMap> = {
  radar: 'radar',
  thermometer: 'thermometer',
  matching: 'map-marker-multiple',
  measuring: 'ruler',
  tentacles: 'asterisk',
};

function answerLabel(answer: string | null): string {
  if (!answer) return '';
  switch (answer) {
    case 'yes':
      return 'Yes';
    case 'no':
      return 'No';
    case 'closer':
      return 'Closer';
    case 'farther':
      return 'Farther';
    default:
      return answer;
  }
}

function paramSummary(entry: SeekerQuestionHistoryEntry, unit: string): string {
  const p = entry.parameters;
  if (p.type === 'radar') return `${p.radius} ${unit}`;
  if (p.type === 'thermometer') return `${p.min_travel} ${unit}`;
  if (p.type === 'matching' || p.type === 'measuring') return p.category.replace(/_/g, ' ');
  if (p.type === 'tentacles') return p.category.replace(/_/g, ' ');
  return '';
}

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
          renderItem={({ item }) => {
            const colors = getTypeColors(item.question_type);
            const icon = QUESTION_TYPE_ICONS[item.question_type] ?? 'help-circle';
            const summary = paramSummary(item, unit);

            return (
              <Pressable
                style={({ pressed }) => [styles.row, pressed && styles.rowPressed]}
                onPress={() => {
                  onSelect(item.sequence - 1);
                  onClose();
                }}
              >
                <View style={[styles.iconCircle, { backgroundColor: colors.active }]}>
                  <MaterialCommunityIcons name={icon} size={18} color={colors.onActive} />
                </View>
                <Text style={styles.sequence}>Q{item.sequence}</Text>
                <Text style={styles.paramSummary}>{summary}</Text>
                <Text style={styles.answer}>{answerLabel(item.answer)}</Text>
              </Pressable>
            );
          }}
          ListFooterComponent={
            <Pressable
              style={({ pressed }) => [styles.row, styles.noneRow, pressed && styles.rowPressed]}
              onPress={() => {
                onSelect(maxSequence);
                onClose();
              }}
            >
              <View style={[styles.iconCircle, { backgroundColor: '#555' }]}>
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
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 12,
    paddingHorizontal: 12,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: 'rgba(255,255,255,0.1)',
  },
  rowPressed: {
    backgroundColor: 'rgba(255,255,255,0.08)',
  },
  iconCircle: {
    width: 32,
    height: 32,
    borderRadius: 16,
    alignItems: 'center',
    justifyContent: 'center',
  },
  sequence: {
    fontSize: 14,
    fontWeight: '600',
    color: 'rgba(255,255,255,0.5)',
    marginLeft: 12,
    width: 32,
  },
  paramSummary: {
    fontSize: 15,
    fontWeight: '500',
    color: '#fff',
    flex: 1,
    marginLeft: 8,
  },
  answer: {
    fontSize: 14,
    fontWeight: '600',
    color: 'rgba(255,255,255,0.7)',
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
