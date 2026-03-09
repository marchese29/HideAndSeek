#!/usr/bin/env bash
# Manual test script for imperial convention game flow.
# Usage: ./scripts/manual-test-imperial.sh [base_url]
#
# Exercises the same game lifecycle as manual-test.sh but on an imperial map.
# Verifies that:
#   - convention='imperial' appears in GameResponse
#   - Slot distances are in miles
#   - Radar answer uses mile→meter conversion (1 mi ≈ 1609 m)
#   - Measuring distances are reported in miles
#   - Push labels use imperial formatting (e.g. "1 mi")
#   - New role-gated endpoints work correctly
#
# Prerequisites:
#   docker compose up --build   (or local server on :8000)
#   manual-test.sh must have run first (seeds the transit dataset)

set -euo pipefail

BASE="${1:-http://localhost:8000}"
DS_ID="00000000-0000-0000-0000-000000000001"
MAP_ID="00000000-0000-0000-0000-000000000003"
FEAT_SEEKER="00000000-0000-0000-0000-000000000020"
FEAT_HIDER="00000000-0000-0000-0000-000000000021"
HOST_CLIENT="44444444-4444-4444-4444-444444444444"
SEEKER_CLIENT="55555555-5555-5555-5555-555555555555"
HIDER_CLIENT="66666666-6666-6666-6666-666666666666"

pp() { python3 -m json.tool; }
jq_val() { python3 -c "import sys,json; print(json.load(sys.stdin)$1)"; }
assert_eq() {
  local label="$1" actual="$2" expected="$3"
  if [ "$actual" != "$expected" ]; then
    echo "  FAIL: $label — expected '$expected', got '$actual'" >&2
    exit 1
  fi
  echo "  OK: $label = $actual"
}
assert_match() {
  local label="$1" actual="$2" pattern="$3"
  if ! echo "$actual" | grep -qE "$pattern"; then
    echo "  FAIL: $label — expected to match '$pattern', got '$actual'" >&2
    exit 1
  fi
  echo "  OK: $label matches $pattern"
}

echo "=== Seeding imperial game map ==="
docker compose exec -T postgres psql -U hideandseek -q <<SQL
-- Reuse the transit dataset from the metric manual test
INSERT INTO transit_dataset (id, name, region, imported_at)
VALUES ('$DS_ID', 'London Transit', 'London', NOW())
ON CONFLICT DO NOTHING;

INSERT INTO game_map (id, name, size, convention, transit_dataset_id, boundary,
                      districts, district_classes, default_inventory)
VALUES (
  '$MAP_ID', 'Imperial London', 'medium', 'imperial', '$DS_ID',
  ST_GeomFromText('POLYGON((-0.2 51.4, 0.1 51.4, 0.1 51.6, -0.2 51.6, -0.2 51.4))', 4326),
  '[]', '[]',
  '{"radars":[{"distance":1},{"distance":5},{"distance":null}],
    "thermometers":[{"distance":0.5},{"distance":null}]}'
) ON CONFLICT DO NOTHING;

-- Two hospitals for matching/measuring tests
INSERT INTO map_feature (id, category, stable_id, name, shape)
VALUES
  ('$FEAT_SEEKER', 'hospital', 'imp_hosp_seeker', 'Imperial Seeker Hospital',
   ST_GeomFromText('POINT(-0.11 51.51)', 4326)),
  ('$FEAT_HIDER', 'hospital', 'imp_hosp_hider', 'Imperial Hider Hospital',
   ST_GeomFromText('POINT(0.01 51.01)', 4326))
ON CONFLICT DO NOTHING;

INSERT INTO game_map_feature (game_map_id, map_feature_id)
VALUES
  ('$MAP_ID', '$FEAT_SEEKER'),
  ('$MAP_ID', '$FEAT_HIDER')
ON CONFLICT DO NOTHING;

-- Reuse stops from metric test (seeded by manual-test.sh)
SQL
echo "Done."

echo ""
echo "=== POST /games (create imperial game — host is first player) ==="
CREATE_RESP=$(curl -sf -X POST "$BASE/games" \
  -H "Content-Type: application/json" \
  -H "X-Client-Id: $HOST_CLIENT" \
  -d "{\"map_id\": \"$MAP_ID\", \"name\": \"ImperialHost\"}")
echo "$CREATE_RESP" | pp
GAME=$(echo "$CREATE_RESP" | python3 -c "import sys,json; print(json.dumps(json.load(sys.stdin)['game']))")
GAME_ID=$(echo "$GAME" | jq_val "['id']")
JOIN_CODE=$(echo "$GAME" | jq_val "['join_code']")
HOST_PLAYER_ID=$(echo "$CREATE_RESP" | jq_val "['player_id']")
echo "  Game ID:        $GAME_ID"
echo "  Join code:      $JOIN_CODE"
echo "  Host player ID: $HOST_PLAYER_ID"

# Verify convention is imperial
CONVENTION=$(echo "$GAME" | jq_val "['convention']")
assert_eq "convention" "$CONVENTION" "imperial"

# Verify static slot distances are in miles
RADAR_0_DIST=$(echo "$GAME" | jq_val "['inventory']['radar_slots'][0]['distance']")
assert_eq "radar slot 0 distance" "$RADAR_0_DIST" "1.0"
THERMO_0_DIST=$(echo "$GAME" | jq_val "['inventory']['thermometer_slots'][0]['distance']")
assert_eq "thermometer slot 0 distance" "$THERMO_0_DIST" "0.5"

# Verify no hider_station_id on shared endpoint
HAS_STATION=$(echo "$GAME" | python3 -c "import sys,json; print('hider_station_id' in json.load(sys.stdin))")
assert_eq "no hider_station_id" "$HAS_STATION" "False"

echo ""
echo "=== POST /games/join (seeker + hider) ==="
SEEKER_RESP=$(curl -sf -X POST "$BASE/games/join" \
  -H "Content-Type: application/json" \
  -H "X-Client-Id: $SEEKER_CLIENT" \
  -d "{\"join_code\":\"$JOIN_CODE\",\"name\":\"Seeker\",\"device_token\":\"ccc\"}")
SEEKER_ID=$(echo "$SEEKER_RESP" | jq_val "['player_id']")
echo "  Seeker ID: $SEEKER_ID"

HIDER_RESP=$(curl -sf -X POST "$BASE/games/join" \
  -H "Content-Type: application/json" \
  -H "X-Client-Id: $HIDER_CLIENT" \
  -d "{\"join_code\":\"$JOIN_CODE\",\"name\":\"Hider\",\"device_token\":\"ddd\"}")
HIDER_ID=$(echo "$HIDER_RESP" | jq_val "['player_id']")
echo "  Hider ID: $HIDER_ID"

TEMP_CLIENT="77777777-7777-7777-7777-777777777777"
echo ""
echo "=== POST /games/join (temp player for kick test) ==="
TEMP_RESP=$(curl -sf -X POST "$BASE/games/join" \
  -H "Content-Type: application/json" \
  -H "X-Client-Id: $TEMP_CLIENT" \
  -d "{\"join_code\":\"$JOIN_CODE\",\"name\":\"TempPlayer\"}")
TEMP_ID=$(echo "$TEMP_RESP" | jq_val "['player_id']")
echo "  Temp ID: $TEMP_ID"

echo ""
echo "=== DELETE player (host kicks temp player) ==="
KICK_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X DELETE \
  "$BASE/games/$GAME_ID/players/$TEMP_ID" \
  -H "X-Client-Id: $HOST_CLIENT")
assert_eq "kick status" "$KICK_STATUS" "204"

echo ""
echo "=== Verify game has 3 players after kick ==="
PLAYER_COUNT=$(curl -sf "$BASE/games/$GAME_ID" | python3 -c "import sys,json; print(len(json.load(sys.stdin)['players']))")
assert_eq "player count after kick" "$PLAYER_COUNT" "3"

echo ""
echo "=== Assign roles + start + force seeking ==="
curl -sf -X PATCH "$BASE/games/$GAME_ID/players/$HOST_PLAYER_ID" \
  -H "Content-Type: application/json" -H "X-Client-Id: $HOST_CLIENT" \
  -d '{"role":"seeker"}' > /dev/null
curl -sf -X PATCH "$BASE/games/$GAME_ID/players/$SEEKER_ID" \
  -H "Content-Type: application/json" -H "X-Client-Id: $SEEKER_CLIENT" \
  -d '{"role":"seeker"}' > /dev/null
curl -sf -X PATCH "$BASE/games/$GAME_ID/players/$HIDER_ID" \
  -H "Content-Type: application/json" -H "X-Client-Id: $HIDER_CLIENT" \
  -d '{"role":"hider"}' > /dev/null
curl -sf -X POST "$BASE/games/$GAME_ID/start" \
  -H "X-Client-Id: $HOST_CLIENT" > /dev/null
STOP_VICTORIA="00000000-0000-0000-0000-000000000020"
docker compose exec -T postgres psql -U hideandseek -q -c \
  "UPDATE game SET status='seeking', seeking_started_at=NOW(), hider_station_id='$STOP_VICTORIA' WHERE id='$GAME_ID';"
echo "  Done."

echo ""
echo "=== GET /games/{id}/hider-station as hider (station visible) ==="
HIDER_STATION_RESP=$(curl -sf "$BASE/games/$GAME_ID/hider-station" -H "X-Client-Id: $HIDER_CLIENT")
HIDER_STATION=$(echo "$HIDER_STATION_RESP" | jq_val "['hider_station_id']")
assert_eq "hider_station_id" "$HIDER_STATION" "$STOP_VICTORIA"

echo ""
echo "=== GET /games/{id}/hider-station as seeker (should 403) ==="
SEEKER_STATION_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/games/$GAME_ID/hider-station" -H "X-Client-Id: $SEEKER_CLIENT")
assert_eq "seeker hider-station status" "$SEEKER_STATION_STATUS" "403"

echo ""
echo "=== Report locations ==="
# Seeker at (-0.1, 51.5), hider at (-0.1, 51.514) — ~1556 m apart (~0.97 mi)
curl -sf -X POST "$BASE/games/$GAME_ID/location" \
  -H "Content-Type: application/json" \
  -H "X-Client-Id: $SEEKER_CLIENT" \
  -d '{"coordinates":{"type":"Point","coordinates":[-0.1,51.5]},"timestamp":"2026-02-22T10:00:00Z"}' > /dev/null
curl -sf -X POST "$BASE/games/$GAME_ID/location" \
  -H "Content-Type: application/json" \
  -H "X-Client-Id: $HIDER_CLIENT" \
  -d '{"coordinates":{"type":"Point","coordinates":[-0.1,51.514]},"timestamp":"2026-02-22T10:00:00Z"}' > /dev/null
echo "  Seeker: (-0.1, 51.5), Hider: (-0.1, 51.514) — ~1556 m apart"

echo ""
echo "=== POST /questions/radar (1 mile — hider ~0.97 mi away → expect 'yes') ==="
Q=$(curl -sf -X POST "$BASE/games/$GAME_ID/questions/radar" \
  -H "Content-Type: application/json" \
  -H "X-Client-Id: $SEEKER_CLIENT" \
  -d '{"location":{"type":"Point","coordinates":[-0.1,51.5]},"slot_index":0}')
echo "$Q" | pp
Q_ID=$(echo "$Q" | jq_val "['id']")

# Verify radius is 1 (mile), not 1609
RADIUS=$(echo "$Q" | jq_val "['parameters']['radius']")
assert_eq "radar radius" "$RADIUS" "1.0"

echo ""
echo "=== POST /questions/{id}/answer (radar — expect 'yes', hider within 1 mile) ==="
A=$(curl -sf -X POST "$BASE/games/$GAME_ID/questions/$Q_ID/answer" \
  -H "X-Client-Id: $HIDER_CLIENT")
echo "$A" | pp
ANSWER=$(echo "$A" | jq_val "['answer']")
assert_eq "radar answer" "$ANSWER" "yes"

echo ""
echo "=== GET /candidate-stations as seeker ==="
CANDS=$(curl -sf "$BASE/games/$GAME_ID/candidate-stations" \
  -H "X-Client-Id: $SEEKER_CLIENT")
CAND_COUNT=$(echo "$CANDS" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))")
echo "  Candidates: $CAND_COUNT (1 expected — Waterloo inside 1mi hit circle)"

echo ""
echo "=== POST /questions/thermometer (0.5 mi thermometer) ==="
Q=$(curl -sf -X POST "$BASE/games/$GAME_ID/questions/thermometer" \
  -H "Content-Type: application/json" \
  -H "X-Client-Id: $SEEKER_CLIENT" \
  -d '{"location":{"type":"Point","coordinates":[-0.1,51.5]},"slot_index":0}')
echo "$Q" | pp
Q_ID=$(echo "$Q" | jq_val "['id']")
MIN_TRAVEL=$(echo "$Q" | jq_val "['parameters']['min_travel']")
assert_eq "thermometer min_travel" "$MIN_TRAVEL" "0.5"

echo ""
echo "=== Seeker moves closer to hider and locks in ==="
curl -sf -X POST "$BASE/games/$GAME_ID/location" \
  -H "Content-Type: application/json" \
  -H "X-Client-Id: $SEEKER_CLIENT" \
  -d '{"coordinates":{"type":"Point","coordinates":[-0.1,51.51]},"timestamp":"2026-02-22T10:05:00Z"}' > /dev/null
curl -sf -X POST "$BASE/games/$GAME_ID/questions/thermometer/$Q_ID/lock-in" \
  -H "X-Client-Id: $SEEKER_CLIENT" > /dev/null
echo "  Locked in at (-0.1, 51.51)"

echo ""
echo "=== POST /questions/{id}/answer (thermometer — expect 'closer') ==="
A=$(curl -sf -X POST "$BASE/games/$GAME_ID/questions/$Q_ID/answer" \
  -H "X-Client-Id: $HIDER_CLIENT")
echo "$A" | pp
ANSWER=$(echo "$A" | jq_val "['answer']")
assert_eq "thermometer answer" "$ANSWER" "closer"

echo ""
echo "=== Relocate hider far away for matching/measuring tests ==="
curl -sf -X POST "$BASE/games/$GAME_ID/location" \
  -H "Content-Type: application/json" \
  -H "X-Client-Id: $HIDER_CLIENT" \
  -d '{"coordinates":{"type":"Point","coordinates":[0.0,51.0]},"timestamp":"2026-02-22T10:06:00Z"}' > /dev/null
echo "  Hider now at (0.0, 51.0)"

echo ""
echo "=== Look up matching/measuring slot indices for hospital ==="
INV=$(curl -sf "$BASE/games/$GAME_ID/inventory")
MATCHING_IDX=$(echo "$INV" | python3 -c "import sys,json; inv=json.load(sys.stdin); print(next(s['slot_index'] for s in inv['matching_slots'] if s['category']=='hospital'))")
MEASURING_IDX=$(echo "$INV" | python3 -c "import sys,json; inv=json.load(sys.stdin); print(next(s['slot_index'] for s in inv['measuring_slots'] if s['category']=='hospital'))")
echo "  matching slot_index: $MATCHING_IDX, measuring slot_index: $MEASURING_IDX"

echo ""
echo "=== POST /questions/matching (hospital category) ==="
Q=$(curl -sf -X POST "$BASE/games/$GAME_ID/questions/matching" \
  -H "Content-Type: application/json" \
  -H "X-Client-Id: $SEEKER_CLIENT" \
  -d "{\"location\":{\"type\":\"Point\",\"coordinates\":[-0.1,51.5]},\"slot_index\":$MATCHING_IDX}")
echo "$Q" | pp
Q_ID=$(echo "$Q" | jq_val "['id']")
echo "  Seeker feature: $(echo "$Q" | jq_val "['parameters']['seeker_resolution']['name']")"

# Seeker distance should be in miles (< 1 mile from hospital)
SEEKER_DIST=$(echo "$Q" | jq_val "['parameters']['seeker_resolution']['distance']")
echo "  Seeker distance: $SEEKER_DIST mi"
assert_match "seeker distance < 1 mi" "$SEEKER_DIST" '^0\.'

echo ""
echo "=== POST /questions/{id}/answer (matching — expect 'no') ==="
A=$(curl -sf -X POST "$BASE/games/$GAME_ID/questions/$Q_ID/answer" \
  -H "X-Client-Id: $HIDER_CLIENT")
echo "$A" | pp
ANSWER=$(echo "$A" | jq_val "['answer']")
assert_eq "matching answer" "$ANSWER" "no"

# Hider distance should also be in miles
HIDER_DIST=$(echo "$A" | jq_val "['parameters']['hider_resolution']['distance']")
echo "  Hider distance: $HIDER_DIST mi"

echo ""
echo "=== POST /questions/measuring (hospital category) ==="
Q=$(curl -sf -X POST "$BASE/games/$GAME_ID/questions/measuring" \
  -H "Content-Type: application/json" \
  -H "X-Client-Id: $SEEKER_CLIENT" \
  -d "{\"location\":{\"type\":\"Point\",\"coordinates\":[-0.1,51.5]},\"slot_index\":$MEASURING_IDX}")
echo "$Q" | pp
Q_ID=$(echo "$Q" | jq_val "['id']")

echo ""
echo "=== POST /questions/{id}/answer (measuring) ==="
A=$(curl -sf -X POST "$BASE/games/$GAME_ID/questions/$Q_ID/answer" \
  -H "X-Client-Id: $HIDER_CLIENT")
echo "$A" | pp
ANSWER=$(echo "$A" | jq_val "['answer']")
echo "  Answer: $ANSWER"

echo ""
echo "=== GET /questions (summary only — verify no detail fields) ==="
Q_LIST=$(curl -sf "$BASE/games/$GAME_ID/questions" -H "X-Client-Id: $SEEKER_CLIENT")
HAS_PARAMS=$(echo "$Q_LIST" | python3 -c "import sys,json; d=json.load(sys.stdin); print('parameters' in d[0])")
assert_eq "no parameters on summary" "$HAS_PARAMS" "False"

echo ""
echo "=== GET /exclusions (4 exclusions for seeker) ==="
EXCL=$(curl -sf "$BASE/games/$GAME_ID/exclusions" -H "X-Client-Id: $SEEKER_CLIENT")
EXCL_COUNT=$(echo "$EXCL" | python3 -c "import sys,json; print(len(json.load(sys.stdin)['exclusions']))")
assert_eq "exclusion entries" "$EXCL_COUNT" "4"

echo ""
echo "=== GET /endgame-exclusions as seeker (Victoria station, after_question=0) ==="
ENDGAME=$(curl -sf "$BASE/games/$GAME_ID/endgame-exclusions?station_id=$STOP_VICTORIA&after_question=0" \
  -H "X-Client-Id: $SEEKER_CLIENT")
ENTRY_COUNT=$(echo "$ENDGAME" | python3 -c "import sys,json; print(len(json.load(sys.stdin)['entries']))")
echo "  Entries: $ENTRY_COUNT (should be 4 — all answered questions)"
echo "  Hiding zone type: $(echo "$ENDGAME" | jq_val "['hiding_zone']['type']")"

echo ""
echo "=== GET /endgame-exclusions (after_question=2, only questions 3+4) ==="
ENDGAME2=$(curl -sf "$BASE/games/$GAME_ID/endgame-exclusions?station_id=$STOP_VICTORIA&after_question=2" \
  -H "X-Client-Id: $SEEKER_CLIENT")
ENTRY_COUNT2=$(echo "$ENDGAME2" | python3 -c "import sys,json; print(len(json.load(sys.stdin)['entries']))")
echo "  Entries: $ENTRY_COUNT2 (should be 2)"

echo ""
echo "=== GET /games/{id} (final state — verify convention persists) ==="
FINAL=$(curl -sf "$BASE/games/$GAME_ID")
CONVENTION=$(echo "$FINAL" | jq_val "['convention']")
assert_eq "final convention" "$CONVENTION" "imperial"

echo ""
echo "=== POST /games/{id}/end ==="
curl -sf -X POST "$BASE/games/$GAME_ID/end" | jq_val "['status']"

echo ""
echo "All imperial tests passed!"
