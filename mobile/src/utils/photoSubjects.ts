import type { MaterialCommunityIcons } from '@expo/vector-icons';

import type { components } from '@/api/schema';

export type PhotoSubject = components['schemas']['PhotoSubject'];

type IconName = keyof typeof MaterialCommunityIcons.glyphMap;

export const PHOTO_SUBJECT_LABELS: Record<PhotoSubject, string> = {
  tree: 'A tree',
  sky: 'The sky',
  selfie: 'A selfie',
  widest_street: 'The widest nearby street',
  tallest_structure_in_sightline: 'The tallest structure in your sightline',
  any_building_from_station: 'Any building visible from your station',
  tallest_building_from_station: 'The tallest building visible from your station',
  nearest_street_trace: 'The nearest street (full trace)',
  two_buildings: 'Two buildings together',
  restaurant_interior: 'A restaurant interior',
  train_platform: 'A train platform',
  park: 'A park',
  grocery_aisle: 'A grocery store aisle',
  place_of_worship: 'A place of worship',
  half_mile_streets_traced: 'Half a mile of streets, traced',
  tallest_mountain_from_station: 'The tallest mountain visible from your station',
  biggest_body_of_water: 'The biggest visible body of water',
  five_buildings: 'Five distinct buildings',
};

export const PHOTO_SUBJECT_SHORT_LABELS: Record<PhotoSubject, string> = {
  tree: 'Tree',
  sky: 'Sky',
  selfie: 'Selfie',
  widest_street: 'Widest street',
  tallest_structure_in_sightline: 'Tallest structure',
  any_building_from_station: 'Any building',
  tallest_building_from_station: 'Tallest building',
  nearest_street_trace: 'Nearest street',
  two_buildings: 'Two buildings',
  restaurant_interior: 'Restaurant',
  train_platform: 'Train platform',
  park: 'Park',
  grocery_aisle: 'Grocery aisle',
  place_of_worship: 'Place of worship',
  half_mile_streets_traced: '½ mi of streets',
  tallest_mountain_from_station: 'Tallest mountain',
  biggest_body_of_water: 'Body of water',
  five_buildings: 'Five buildings',
};

export const PHOTO_SUBJECT_ICONS: Record<PhotoSubject, IconName> = {
  tree: 'tree',
  sky: 'weather-sunny',
  selfie: 'camera-front',
  widest_street: 'road',
  tallest_structure_in_sightline: 'tower-fire',
  any_building_from_station: 'office-building',
  tallest_building_from_station: 'office-building',
  nearest_street_trace: 'map-marker-path',
  two_buildings: 'office-building-outline',
  restaurant_interior: 'silverware-fork-knife',
  train_platform: 'train',
  park: 'pine-tree',
  grocery_aisle: 'cart',
  place_of_worship: 'church',
  half_mile_streets_traced: 'map-marker-distance',
  tallest_mountain_from_station: 'image-filter-hdr',
  biggest_body_of_water: 'water',
  five_buildings: 'domain',
};

export function photoSubjectIcon(subject: string | null | undefined): IconName {
  if (!subject) return 'camera';
  return (PHOTO_SUBJECT_ICONS as Record<string, IconName>)[subject] ?? 'camera';
}

export function photoSubjectLabel(subject: string | null | undefined): string {
  if (!subject) return 'Photo';
  return (PHOTO_SUBJECT_LABELS as Record<string, string>)[subject] ?? subject;
}

export function photoSubjectShortLabel(subject: string | null | undefined): string {
  if (!subject) return 'Photo';
  return (PHOTO_SUBJECT_SHORT_LABELS as Record<string, string>)[subject] ?? subject;
}
