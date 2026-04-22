import { MaterialCommunityIcons } from '@expo/vector-icons';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { getTypeColors } from '@/constants/questionColors';
import type { HiderQuestionHistoryEntry } from '@/types/gameplay';

export const QUESTION_TYPE_ICONS: Record<string, keyof typeof MaterialCommunityIcons.glyphMap> = {
  radar: 'radar',
  thermometer: 'thermometer',
  matching: 'map-marker-multiple',
  measuring: 'ruler',
  tentacles: 'asterisk',
};

export function answerLabel(answer: string | null): string {
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

export type QuestionHistoryRowEntry = {
  question_id: string;
  sequence: number;
  question_type: string;
  parameters: HiderQuestionHistoryEntry['parameters'];
  answer: string | null;
  status: string;
};

export function paramSummary(entry: QuestionHistoryRowEntry, unit: string): string {
  // Key off question_type (canonical) rather than entry.parameters.type — the event
  // discriminator is "feature" for matching/measuring while the response discriminator
  // is "matching"/"measuring", so reading p.type misses the event-shaped placeholder.
  const p = entry.parameters as Record<string, unknown>;
  switch (entry.question_type) {
    case 'radar':
      return `${p.radius} ${unit}`;
    case 'thermometer':
      return `${p.min_travel} ${unit}`;
    case 'matching':
    case 'measuring':
    case 'tentacles':
      return String(p.category ?? '').replace(/_/g, ' ');
    default:
      return '';
  }
}

interface QuestionHistoryRowProps {
  entry: QuestionHistoryRowEntry;
  unit: string;
  onPress?: () => void;
}

export function QuestionHistoryRow({ entry, unit, onPress }: QuestionHistoryRowProps) {
  const colors = getTypeColors(entry.question_type);
  const icon = QUESTION_TYPE_ICONS[entry.question_type] ?? 'help-circle';
  const summary = paramSummary(entry, unit);

  const inner = (
    <>
      <View style={[questionHistoryRowStyles.iconCircle, { backgroundColor: colors.active }]}>
        <MaterialCommunityIcons name={icon} size={18} color={colors.onActive} />
      </View>
      <Text style={questionHistoryRowStyles.sequence}>Q{entry.sequence}</Text>
      <Text style={questionHistoryRowStyles.paramSummary}>{summary}</Text>
      {entry.status === 'answered' ? (
        <Text style={questionHistoryRowStyles.answer}>{answerLabel(entry.answer)}</Text>
      ) : (
        <Text style={questionHistoryRowStyles.statusLabel}>
          {entry.status === 'vetoed' ? 'Vetoed' : 'Abandoned'}
        </Text>
      )}
    </>
  );

  if (onPress) {
    return (
      <Pressable
        style={({ pressed }) => [
          questionHistoryRowStyles.row,
          pressed && questionHistoryRowStyles.rowPressed,
        ]}
        onPress={onPress}
      >
        {inner}
      </Pressable>
    );
  }
  return <View style={questionHistoryRowStyles.row}>{inner}</View>;
}

export const questionHistoryRowStyles = StyleSheet.create({
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
  statusLabel: {
    fontSize: 14,
    fontWeight: '500',
    fontStyle: 'italic',
    color: 'rgba(255,255,255,0.5)',
  },
});
