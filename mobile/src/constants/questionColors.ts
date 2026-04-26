export interface QuestionTypeColors {
  /** RGB tuple for map overlay rgba() strings. */
  rgb: [number, number, number];
  /** CSS color for active UI elements (buttons, belt pills). */
  active: string;
  /** CSS color for inactive/dimmed UI elements. */
  inactive: string;
  /** Text/icon color for readability on the active background. */
  onActive: string;
}

const QUESTION_TYPE_COLORS: Record<string, QuestionTypeColors> = {
  radar: {
    rgb: [245, 121, 59],
    active: 'rgb(245, 121, 59)',
    inactive: 'rgb(242, 181, 150)',
    onActive: '#fff',
  },
  thermometer: {
    rgb: [255, 191, 65],
    active: 'rgb(255, 191, 65)',
    inactive: 'rgb(248, 215, 152)',
    onActive: '#1a1a1a',
  },
  matching: {
    rgb: [33, 47, 64],
    active: 'rgb(33, 47, 64)',
    inactive: 'rgb(135, 143, 151)',
    onActive: '#fff',
  },
  measuring: {
    rgb: [77, 162, 100],
    active: 'rgb(77, 162, 100)',
    inactive: 'rgb(158, 201, 169)',
    onActive: '#fff',
  },
  tentacles: {
    rgb: [138, 92, 199],
    active: 'rgb(138, 92, 199)',
    inactive: 'rgb(183, 152, 217)',
    onActive: '#fff',
  },
  photo: {
    rgb: [156, 190, 208],
    active: 'rgb(156, 190, 208)',
    inactive: 'rgb(199, 216, 225)',
    onActive: '#fff',
  },
};

const FALLBACK = QUESTION_TYPE_COLORS.matching;

/** Lighter matching shade for banner backgrounds (distinct from the dark belt). */
const MATCHING_BANNER = 'rgb(52, 73, 94)';

/** Look up colors for a question type. Falls back to matching (dark gray). */
export function getTypeColors(type: string): QuestionTypeColors {
  return QUESTION_TYPE_COLORS[type] ?? FALLBACK;
}

/**
 * Banner-specific background color for a question type.
 * Matching uses a lighter shade so the banner is visually distinct from the
 * dark utility belt. All other types use their normal active color.
 */
export function getBannerColor(type: string): string {
  if (type === 'matching') return MATCHING_BANNER;
  return getTypeColors(type).active;
}
