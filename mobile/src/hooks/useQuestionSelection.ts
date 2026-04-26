import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react';

import { useGameplayStore } from '@/stores/gameplayStore';
import type { InventorySlotResponse, PreviewQuestion } from '@/types/gameplay';

// ── State machine ────────────────────────────────────────────────────────────

type SelectionState =
  | { step: 'closed' }
  | { step: 'type' }
  | { step: 'param'; questionType: string }
  | { step: 'custom'; questionType: string };

type SelectionAction =
  | { type: 'toggle' }
  | { type: 'select_type'; questionType: string }
  | { type: 'select_param' }
  | { type: 'open_custom'; questionType: string }
  | { type: 'submit_custom' }
  | { type: 'close' };

function reducer(state: SelectionState, action: SelectionAction): SelectionState {
  switch (action.type) {
    case 'toggle':
      return state.step === 'closed' ? { step: 'type' } : { step: 'closed' };
    case 'select_type':
      // Same type tapped again → back to type selection
      if (state.step === 'param' && state.questionType === action.questionType) {
        return { step: 'type' };
      }
      return { step: 'param', questionType: action.questionType };
    case 'select_param':
      return state; // Stay in param step — preview is set via store
    case 'open_custom':
      return { step: 'custom', questionType: action.questionType };
    case 'submit_custom':
      // Return to param step after custom submission
      if (state.step === 'custom') {
        return { step: 'param', questionType: state.questionType };
      }
      return state;
    case 'close':
      return { step: 'closed' };
  }
}

// ── Preview builders ─────────────────────────────────────────────────────────

function buildPreview(slot: InventorySlotResponse): PreviewQuestion {
  switch (slot.question_type) {
    case 'radar':
      return {
        question_type: 'radar',
        slot_index: slot.slot_index,
        parameters: { type: 'radar', radius: slot.distance! },
      };
    case 'thermometer':
      return {
        question_type: 'thermometer',
        slot_index: slot.slot_index,
        parameters: { type: 'thermometer', min_travel: slot.distance! },
      };
    case 'tentacles':
      return {
        question_type: 'tentacles',
        slot_index: slot.slot_index,
        parameters: {
          type: 'tentacles',
          category: slot.category!,
          distance: slot.distance!,
          poi_ids: [],
          poi_names: [],
        },
      };
    case 'photo':
      return {
        question_type: 'photo',
        slot_index: slot.slot_index,
        parameters: { type: 'photo', subject: slot.photo_subject! },
      };
    default:
      // matching / measuring
      return {
        question_type: slot.question_type,
        slot_index: slot.slot_index,
        parameters: {
          type: 'feature',
          category: slot.category!,
          feature_class: slot.feature_class,
          source: '',
          seeker_feature_id: '',
          seeker_feature_name: '',
          seeker_distance: 0,
        },
      };
  }
}

function buildCustomPreview(
  questionType: string,
  slot: InventorySlotResponse,
  distance: number,
): PreviewQuestion {
  const params =
    questionType === 'thermometer'
      ? ({ type: 'thermometer', min_travel: distance } as const)
      : ({ type: 'radar', radius: distance } as const);
  return {
    question_type: questionType,
    slot_index: slot.slot_index,
    parameters: params,
    custom_distance: distance,
  };
}

// ── Hook ─────────────────────────────────────────────────────────────────────

export interface QuestionSelection {
  state: SelectionState;
  isOpen: boolean;
  slotsForType: InventorySlotResponse[];
  selectedSlotIndex: number | null;
  toggle: () => void;
  selectType: (questionType: string) => void;
  selectSlot: (slot: InventorySlotResponse) => void;
  openCustom: () => void;
  submitCustom: (distance: number) => void;
  close: () => void;
}

export function useQuestionSelection(
  inventory: InventorySlotResponse[],
  hasActiveQuestion: boolean,
): QuestionSelection {
  const [state, dispatch] = useReducer(reducer, { step: 'closed' });
  const [selectedSlotIndex, setSelectedSlotIndex] = useState<number | null>(null);

  const setPreviewQuestion = useGameplayStore((s) => s.setPreviewQuestion);

  // Dismiss selection when a question is asked (rising edge only).
  // Intentionally does NOT clear previewQuestion — the surviving preview
  // gets "promoted" to askable once the answer lands.
  const prevHadActive = useRef(hasActiveQuestion);
  useEffect(() => {
    if (hasActiveQuestion && !prevHadActive.current) {
      setSelectedSlotIndex(null);
      dispatch({ type: 'close' });
    }
    prevHadActive.current = hasActiveQuestion;
  }, [hasActiveQuestion]);

  const slotsForType = useMemo(() => {
    if (state.step !== 'param' && state.step !== 'custom') return [];
    return inventory
      .filter((s) => s.question_type === state.questionType)
      .sort((a, b) => {
        // Custom slot (distance === null) sorts last
        if (a.distance === null && b.distance === null) return 0;
        if (a.distance === null) return 1;
        if (b.distance === null) return -1;
        return a.distance - b.distance;
      });
  }, [inventory, state]);

  const toggle = useCallback(() => {
    if (state.step !== 'closed') {
      setPreviewQuestion(null);
      setSelectedSlotIndex(null);
    }
    dispatch({ type: 'toggle' });
  }, [state.step, setPreviewQuestion]);

  const selectType = useCallback(
    (questionType: string) => {
      setPreviewQuestion(null);
      setSelectedSlotIndex(null);
      dispatch({ type: 'select_type', questionType });
    },
    [setPreviewQuestion],
  );

  const selectSlot = useCallback(
    (slot: InventorySlotResponse) => {
      // Toggle off if already selected
      if (selectedSlotIndex === slot.slot_index) {
        setSelectedSlotIndex(null);
        setPreviewQuestion(null);
      } else {
        setSelectedSlotIndex(slot.slot_index);
        setPreviewQuestion(buildPreview(slot));
      }
      dispatch({ type: 'select_param' });
    },
    [setPreviewQuestion, selectedSlotIndex],
  );

  const openCustom = useCallback(() => {
    if (state.step === 'param') {
      dispatch({ type: 'open_custom', questionType: state.questionType });
    }
  }, [state]);

  const submitCustom = useCallback(
    (distance: number) => {
      if (state.step !== 'custom') return;
      // Find the custom slot (distance === null) for this type
      const customSlot = inventory.find(
        (s) => s.question_type === state.questionType && s.distance === null,
      );
      if (customSlot) {
        setPreviewQuestion(buildCustomPreview(state.questionType, customSlot, distance));
      }
      dispatch({ type: 'submit_custom' });
    },
    [state, inventory, setPreviewQuestion],
  );

  const close = useCallback(() => {
    setPreviewQuestion(null);
    setSelectedSlotIndex(null);
    dispatch({ type: 'close' });
  }, [setPreviewQuestion]);

  return {
    state,
    isOpen: state.step !== 'closed',
    slotsForType,
    selectedSlotIndex,
    toggle,
    selectType,
    selectSlot,
    openCustom,
    submitCustom,
    close,
  };
}
