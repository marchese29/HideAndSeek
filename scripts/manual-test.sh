#!/usr/bin/env bash
# Manual test script for the game flow against a running server.
# Usage: ./scripts/manual-test.sh [base_url]
#
# Prerequisites:
#   docker compose up --build   (or local server on :8000)
#
# For Docker, the DB starts empty — this script seeds a transit dataset
# and game map via psql, then runs the full game flow through the API.

set -euo pipefail

BASE="${1:-http://localhost:8000}"
DS_ID="00000000-0000-0000-0000-000000000001"
MAP_ID="00000000-0000-0000-0000-000000000002"
FEAT_SEEKER="00000000-0000-0000-0000-000000000010"
FEAT_HIDER="00000000-0000-0000-0000-000000000011"
HOST_CLIENT="11111111-1111-1111-1111-111111111111"
SEEKER_CLIENT="22222222-2222-2222-2222-222222222222"
HIDER_CLIENT="33333333-3333-3333-3333-333333333333"

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

echo "=== Seeding transit dataset + game map ==="
docker compose exec -T postgres psql -U hideandseek -q <<SQL
INSERT INTO transit_dataset (id, name, region, imported_at)
VALUES ('$DS_ID', 'London Transit', 'London', NOW())
ON CONFLICT DO NOTHING;

INSERT INTO game_map (id, name, size, convention, transit_dataset_id, boundary,
                      districts, district_classes, default_inventory)
VALUES (
  '$MAP_ID', 'Central London', 'medium', 'metric', '$DS_ID',
  ST_GeomFromText('POLYGON((-0.2 51.4, 0.1 51.4, 0.1 51.6, -0.2 51.6, -0.2 51.4))', 4326),
  '[]', '[]',
  '{"radars":[{"distance":3000},{"distance":5000},{"distance":null}],
    "thermometers":[{"distance":500},{"distance":null}]}'
) ON CONFLICT DO NOTHING;
-- Seed two hospital features: one near the seeker, one near the hider
INSERT INTO map_feature (id, category, stable_id, name, shape)
VALUES
  ('$FEAT_SEEKER', 'hospital', 'hosp_near_seeker', 'Seeker Hospital',
   ST_GeomFromText('POINT(-0.11 51.51)', 4326)),
  ('$FEAT_HIDER', 'hospital', 'hosp_near_hider', 'Hider Hospital',
   ST_GeomFromText('POINT(0.01 51.01)', 4326))
ON CONFLICT DO NOTHING;

INSERT INTO game_map_feature (game_map_id, map_feature_id)
VALUES
  ('$MAP_ID', '$FEAT_SEEKER'),
  ('$MAP_ID', '$FEAT_HIDER')
ON CONFLICT DO NOTHING;

-- Seed transit stops for candidate stations / endgame testing
INSERT INTO stop (id, stable_id, dataset_id, name, coordinates) VALUES
  ('00000000-0000-0000-0000-000000000020', 'victoria',   '$DS_ID', 'Victoria',   ST_SetSRID(ST_MakePoint(-0.1437, 51.4952), 4326)),
  ('00000000-0000-0000-0000-000000000021', 'paddington', '$DS_ID', 'Paddington', ST_SetSRID(ST_MakePoint(-0.1756, 51.5154), 4326)),
  ('00000000-0000-0000-0000-000000000022', 'waterloo',   '$DS_ID', 'Waterloo',   ST_SetSRID(ST_MakePoint(-0.1134, 51.5031), 4326))
ON CONFLICT DO NOTHING;
SQL
echo "Done."

echo ""
echo "=== GET /maps ==="
curl -sf "$BASE/maps" | pp

echo ""
echo "=== GET /maps/$MAP_ID (boundary should be GeoJSON Polygon) ==="
curl -sf "$BASE/maps/$MAP_ID" | pp

echo ""
echo "=== POST /games (create game — host is first player) ==="
CREATE_RESP=$(curl -sf -X POST "$BASE/games" \
  -H "Content-Type: application/json" \
  -H "X-Client-Id: $HOST_CLIENT" \
  -d "{\"map_id\": \"$MAP_ID\", \"name\": \"Host\"}")
echo "$CREATE_RESP" | pp
GAME=$(echo "$CREATE_RESP" | python3 -c "import sys,json; print(json.dumps(json.load(sys.stdin)['game']))")
GAME_ID=$(echo "$GAME" | jq_val "['id']")
JOIN_CODE=$(echo "$GAME" | jq_val "['join_code']")
HOST_PLAYER_ID=$(echo "$CREATE_RESP" | jq_val "['player_id']")
echo "  Game ID:        $GAME_ID"
echo "  Join code:      $JOIN_CODE"
echo "  Host player ID: $HOST_PLAYER_ID"

# Verify host is in players with server-assigned color
HOST_COLOR=$(echo "$GAME" | jq_val "['players'][0]['color']")
assert_eq "host color" "$HOST_COLOR" "red"
HOST_NAME=$(echo "$GAME" | jq_val "['players'][0]['name']")
assert_eq "host name" "$HOST_NAME" "Host"

# Verify static inventory (no IDs, no consumed flags)
echo ""
echo "=== Verify static inventory ==="
RADAR_0=$(echo "$GAME" | jq_val "['inventory']['radar_slots'][0]")
echo "  radar_slots[0]: $RADAR_0"
# Should have matching_slots
MATCHING=$(echo "$GAME" | jq_val "['inventory']['matching_slots']")
echo "  matching_slots: $MATCHING"
# Should NOT have hider_station_id
HAS_STATION=$(echo "$GAME" | python3 -c "import sys,json; print('hider_station_id' in json.load(sys.stdin))")
assert_eq "no hider_station_id on shared endpoint" "$HAS_STATION" "False"

echo ""
echo "=== POST /games/join (seeker) ==="
SEEKER_RESP=$(curl -sf -X POST "$BASE/games/join" \
  -H "Content-Type: application/json" \
  -H "X-Client-Id: $SEEKER_CLIENT" \
  -d "{\"join_code\":\"$JOIN_CODE\",\"name\":\"Seeker\",\"device_token\":\"aaa\"}")
SEEKER_ID=$(echo "$SEEKER_RESP" | jq_val "['player_id']")
echo "  Seeker ID: $SEEKER_ID"

echo ""
echo "=== POST /games/join (hider) ==="
HIDER_RESP=$(curl -sf -X POST "$BASE/games/join" \
  -H "Content-Type: application/json" \
  -H "X-Client-Id: $HIDER_CLIENT" \
  -d "{\"join_code\":\"$JOIN_CODE\",\"name\":\"Hider\",\"device_token\":\"bbb\"}")
HIDER_ID=$(echo "$HIDER_RESP" | jq_val "['player_id']")
echo "  Hider ID: $HIDER_ID"

echo ""
echo "=== PATCH players (assign roles — host + joined players) ==="
curl -sf -X PATCH "$BASE/games/$GAME_ID/players/$HOST_PLAYER_ID" \
  -H "Content-Type: application/json" -H "X-Client-Id: $HOST_CLIENT" \
  -d '{"role":"seeker"}' | jq_val "['role']"
curl -sf -X PATCH "$BASE/games/$GAME_ID/players/$SEEKER_ID" \
  -H "Content-Type: application/json" -H "X-Client-Id: $SEEKER_CLIENT" \
  -d '{"role":"seeker"}' | jq_val "['role']"
curl -sf -X PATCH "$BASE/games/$GAME_ID/players/$HIDER_ID" \
  -H "Content-Type: application/json" -H "X-Client-Id: $HIDER_CLIENT" \
  -d '{"role":"hider"}' | jq_val "['role']"

echo ""
echo "=== POST /games/{id}/start (host-only) ==="
curl -sf -X POST "$BASE/games/$GAME_ID/start" \
  -H "X-Client-Id: $HOST_CLIENT" | jq_val "['status']"

STOP_VICTORIA="00000000-0000-0000-0000-000000000020"

echo ""
echo "=== Forcing transition to seeking (skip hiding timer) ==="
docker compose exec -T postgres psql -U hideandseek -q -c \
  "UPDATE game SET status='seeking', seeking_started_at=NOW(), hider_station_id='$STOP_VICTORIA' WHERE id='$GAME_ID';"

echo ""
echo "=== GET /games/{id} (no hider_station_id on shared endpoint) ==="
SHARED_VIEW=$(curl -sf "$BASE/games/$GAME_ID")
HAS_STATION=$(echo "$SHARED_VIEW" | python3 -c "import sys,json; print('hider_station_id' in json.load(sys.stdin))")
assert_eq "no hider_station_id" "$HAS_STATION" "False"

echo ""
echo "=== GET /games/{id}/hider-station as hider (should see station) ==="
HIDER_STATION_RESP=$(curl -sf "$BASE/games/$GAME_ID/hider-station" -H "X-Client-Id: $HIDER_CLIENT")
HIDER_STATION=$(echo "$HIDER_STATION_RESP" | jq_val "['hider_station_id']")
assert_eq "hider_station_id" "$HIDER_STATION" "$STOP_VICTORIA"

echo ""
echo "=== GET /games/{id}/hider-station as seeker (should 403) ==="
SEEKER_STATION_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/games/$GAME_ID/hider-station" -H "X-Client-Id: $SEEKER_CLIENT")
assert_eq "seeker hider-station status" "$SEEKER_STATION_STATUS" "403"

echo ""
echo "=== POST /location (seeker at -0.1, 51.5) ==="
curl -sf -X POST "$BASE/games/$GAME_ID/location" \
  -H "Content-Type: application/json" \
  -H "X-Client-Id: $SEEKER_CLIENT" \
  -d '{"coordinates":{"type":"Point","coordinates":[-0.1,51.5]},"timestamp":"2026-02-17T10:00:00Z"}' | pp

echo ""
echo "=== POST /location (hider at 0.0, 51.0) ==="
curl -sf -X POST "$BASE/games/$GAME_ID/location" \
  -H "Content-Type: application/json" \
  -H "X-Client-Id: $HIDER_CLIENT" \
  -d '{"coordinates":{"type":"Point","coordinates":[0.0,51.0]},"timestamp":"2026-02-17T10:01:00Z"}' | pp

echo ""
echo "=== POST /questions/radar (3km radar) ==="
Q=$(curl -sf -X POST "$BASE/games/$GAME_ID/questions/radar" \
  -H "Content-Type: application/json" \
  -H "X-Client-Id: $SEEKER_CLIENT" \
  -d '{"location":{"type":"Point","coordinates":[-0.1,51.5]},"slot_index":0}')
echo "$Q" | pp
Q_ID=$(echo "$Q" | jq_val "['id']")
# Detail response should not have exclusion fields
HAS_EXCL=$(echo "$Q" | python3 -c "import sys,json; print('exclusion' in json.load(sys.stdin))")
assert_eq "no exclusion on detail response" "$HAS_EXCL" "False"

echo ""
echo "=== GET /questions/{id} as hider (question detail) ==="
Q_DETAIL=$(curl -sf "$BASE/games/$GAME_ID/questions/$Q_ID" -H "X-Client-Id: $HIDER_CLIENT")
echo "$Q_DETAIL" | pp
assert_eq "detail has parameters" "$(echo "$Q_DETAIL" | python3 -c "import sys,json; print('parameters' in json.load(sys.stdin))")" "True"

echo ""
echo "=== GET /questions/{id} as seeker (should 403) ==="
Q_DETAIL_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/games/$GAME_ID/questions/$Q_ID" -H "X-Client-Id: $SEEKER_CLIENT")
assert_eq "seeker question detail status" "$Q_DETAIL_STATUS" "403"

echo ""
echo "=== POST /questions/{id}/answer (hider answers — expect 'no', ~56km apart) ==="
curl -sf -X POST "$BASE/games/$GAME_ID/questions/$Q_ID/answer" \
  -H "X-Client-Id: $HIDER_CLIENT" | pp

echo ""
echo "=== GET /exclusions as seeker (should have 1 entry) ==="
EXCL=$(curl -sf "$BASE/games/$GAME_ID/exclusions" -H "X-Client-Id: $SEEKER_CLIENT")
EXCL_COUNT=$(echo "$EXCL" | python3 -c "import sys,json; print(len(json.load(sys.stdin)['exclusions']))")
assert_eq "exclusion entries" "$EXCL_COUNT" "1"

echo ""
echo "=== GET /exclusions as hider (should 403) ==="
EXCL_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/games/$GAME_ID/exclusions" -H "X-Client-Id: $HIDER_CLIENT")
assert_eq "hider exclusions status" "$EXCL_STATUS" "403"

echo ""
echo "=== GET /candidate-stations as seeker ==="
CANDS=$(curl -sf "$BASE/games/$GAME_ID/candidate-stations" \
  -H "X-Client-Id: $SEEKER_CLIENT")
CAND_COUNT=$(echo "$CANDS" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))")
echo "  Candidates: $CAND_COUNT (2 expected — Waterloo hiding zone covered by 3km radar miss)"

echo ""
echo "=== GET /candidate-stations as hider (should 403) ==="
CAND_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/games/$GAME_ID/candidate-stations" -H "X-Client-Id: $HIDER_CLIENT")
assert_eq "hider candidate-stations status" "$CAND_STATUS" "403"

echo ""
echo "=== POST /questions/thermometer (500m thermometer) ==="
Q=$(curl -sf -X POST "$BASE/games/$GAME_ID/questions/thermometer" \
  -H "Content-Type: application/json" \
  -H "X-Client-Id: $SEEKER_CLIENT" \
  -d '{"location":{"type":"Point","coordinates":[-0.1,51.5]},"slot_index":0}')
echo "$Q" | pp
Q_ID=$(echo "$Q" | jq_val "['id']")
echo "  Status should be 'in_progress': $(echo "$Q" | jq_val "['status']")"

echo ""
echo "=== POST /location (seeker moves closer to hider → -0.05, 51.3) ==="
curl -sf -X POST "$BASE/games/$GAME_ID/location" \
  -H "Content-Type: application/json" \
  -H "X-Client-Id: $SEEKER_CLIENT" \
  -d '{"coordinates":{"type":"Point","coordinates":[-0.05,51.3]},"timestamp":"2026-02-17T10:05:00Z"}' | pp

echo ""
echo "=== POST /questions/thermometer/{id}/lock-in ==="
curl -sf -X POST "$BASE/games/$GAME_ID/questions/thermometer/$Q_ID/lock-in" \
  -H "X-Client-Id: $SEEKER_CLIENT" | pp

echo ""
echo "=== POST /questions/{id}/answer (thermometer — expect 'closer') ==="
curl -sf -X POST "$BASE/games/$GAME_ID/questions/$Q_ID/answer" \
  -H "X-Client-Id: $HIDER_CLIENT" | pp

echo ""
echo "=== Look up matching slot_index for hospital ==="
INV=$(curl -sf "$BASE/games/$GAME_ID/inventory")
MATCHING_IDX=$(echo "$INV" | python3 -c "import sys,json; inv=json.load(sys.stdin); print(next(s['slot_index'] for s in inv['matching_slots'] if s['category']=='hospital'))")
echo "  matching slot_index for hospital: $MATCHING_IDX"

echo ""
echo "=== POST /questions/matching (hospital category) ==="
Q=$(curl -sf -X POST "$BASE/games/$GAME_ID/questions/matching" \
  -H "Content-Type: application/json" \
  -H "X-Client-Id: $SEEKER_CLIENT" \
  -d "{\"location\":{\"type\":\"Point\",\"coordinates\":[-0.1,51.5]},\"slot_index\":$MATCHING_IDX}")
echo "$Q" | pp
Q_ID=$(echo "$Q" | jq_val "['id']")
echo "  Seeker feature: $(echo "$Q" | jq_val "['parameters']['seeker_resolution']['name']")"

echo ""
echo "=== POST /questions/{id}/answer (matching — expect 'no', different hospitals) ==="
curl -sf -X POST "$BASE/games/$GAME_ID/questions/$Q_ID/answer" \
  -H "X-Client-Id: $HIDER_CLIENT" | pp

echo ""
echo "=== Look up measuring slot_index for hospital ==="
MEASURING_IDX=$(echo "$INV" | python3 -c "import sys,json; inv=json.load(sys.stdin); print(next(s['slot_index'] for s in inv['measuring_slots'] if s['category']=='hospital'))")
echo "  measuring slot_index for hospital: $MEASURING_IDX"

echo ""
echo "=== POST /questions/measuring (hospital category) ==="
Q=$(curl -sf -X POST "$BASE/games/$GAME_ID/questions/measuring" \
  -H "Content-Type: application/json" \
  -H "X-Client-Id: $SEEKER_CLIENT" \
  -d "{\"location\":{\"type\":\"Point\",\"coordinates\":[-0.1,51.5]},\"slot_index\":$MEASURING_IDX}")
echo "$Q" | pp
Q_ID=$(echo "$Q" | jq_val "['id']")

echo ""
echo "=== POST /questions/{id}/answer (measuring — seeker vs hider distance) ==="
curl -sf -X POST "$BASE/games/$GAME_ID/questions/$Q_ID/answer" \
  -H "X-Client-Id: $HIDER_CLIENT" | pp

echo ""
echo "=== GET /questions (summary only — no params, no locations, no geometry) ==="
Q_LIST=$(curl -sf "$BASE/games/$GAME_ID/questions" \
  -H "X-Client-Id: $SEEKER_CLIENT")
echo "$Q_LIST" | pp
HAS_PARAMS=$(echo "$Q_LIST" | python3 -c "import sys,json; d=json.load(sys.stdin); print('parameters' in d[0])")
assert_eq "no parameters on summary" "$HAS_PARAMS" "False"
HAS_HIDER_LOC=$(echo "$Q_LIST" | python3 -c "import sys,json; d=json.load(sys.stdin); print('hider_location' in d[0])")
assert_eq "no hider_location on summary" "$HAS_HIDER_LOC" "False"

echo ""
echo "=== GET /exclusions (all 4 exclusions for seeker) ==="
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
echo "=== GET /endgame-exclusions as hider (should 403) ==="
ENDGAME_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/games/$GAME_ID/endgame-exclusions?station_id=$STOP_VICTORIA&after_question=0" -H "X-Client-Id: $HIDER_CLIENT")
assert_eq "hider endgame-exclusions status" "$ENDGAME_STATUS" "403"

echo ""
echo "=== GET /endgame-exclusions (after_question=2, only questions 3+4) ==="
ENDGAME2=$(curl -sf "$BASE/games/$GAME_ID/endgame-exclusions?station_id=$STOP_VICTORIA&after_question=2" \
  -H "X-Client-Id: $SEEKER_CLIENT")
ENTRY_COUNT2=$(echo "$ENDGAME2" | python3 -c "import sys,json; print(len(json.load(sys.stdin)['entries']))")
echo "  Entries: $ENTRY_COUNT2 (should be 2)"

echo ""
echo "=== POST /games/{id}/end ==="
curl -sf -X POST "$BASE/games/$GAME_ID/end" | jq_val "['status']"

echo ""
echo "=== GET /location-history (post-game replay) ==="
curl -sf "$BASE/games/$GAME_ID/location-history" | pp

echo ""
echo "All done!"
