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

echo "=== Seeding transit dataset + game map ==="
docker compose exec -T postgres psql -U hideandseek -q <<SQL
INSERT INTO transit_dataset (id, name, region, imported_at)
VALUES ('$DS_ID', 'London Transit', 'London', NOW())
ON CONFLICT DO NOTHING;

INSERT INTO game_map (id, name, size, convention, transit_dataset_id, boundary,
                      excluded_stop_ids, excluded_route_ids, districts,
                      district_classes, feature_classes, default_inventory)
VALUES (
  '$MAP_ID', 'Central London', 'medium', 'metric', '$DS_ID',
  ST_GeomFromText('POLYGON((-0.2 51.4, 0.1 51.4, 0.1 51.6, -0.2 51.6, -0.2 51.4))', 4326),
  '[]', '[]', '[]', '[]', '{}',
  '{"radars":[{"distance":3000},{"distance":5000},{"distance":null}],
    "thermometers":[{"distance":500},{"distance":null}]}'
) ON CONFLICT DO NOTHING;
-- Seed two hospital features: one near the seeker, one near the hider
INSERT INTO map_feature (id, category, stable_id, name, geometry)
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
echo "=== POST /games (create game) ==="
GAME=$(curl -sf -X POST "$BASE/games" \
  -H "Content-Type: application/json" \
  -H "X-Client-Id: $HOST_CLIENT" \
  -d "{\"map_id\": \"$MAP_ID\"}")
echo "$GAME" | pp
GAME_ID=$(echo "$GAME" | jq_val "['id']")
JOIN_CODE=$(echo "$GAME" | jq_val "['join_code']")
echo "  Game ID:   $GAME_ID"
echo "  Join code: $JOIN_CODE"

echo ""
echo "=== POST /games/join (seeker) ==="
SEEKER_RESP=$(curl -sf -X POST "$BASE/games/join" \
  -H "Content-Type: application/json" \
  -H "X-Client-Id: $SEEKER_CLIENT" \
  -d "{\"join_code\":\"$JOIN_CODE\",\"name\":\"Seeker\",\"color\":\"#0000FF\",\"device_token\":\"aaa\"}")
SEEKER_ID=$(echo "$SEEKER_RESP" | jq_val "['player_id']")
echo "  Seeker ID: $SEEKER_ID"

echo ""
echo "=== POST /games/join (hider) ==="
HIDER_RESP=$(curl -sf -X POST "$BASE/games/join" \
  -H "Content-Type: application/json" \
  -H "X-Client-Id: $HIDER_CLIENT" \
  -d "{\"join_code\":\"$JOIN_CODE\",\"name\":\"Hider\",\"color\":\"#FF0000\",\"device_token\":\"bbb\"}")
HIDER_ID=$(echo "$HIDER_RESP" | jq_val "['player_id']")
echo "  Hider ID: $HIDER_ID"

echo ""
echo "=== PATCH players (assign roles) ==="
curl -sf -X PATCH "$BASE/games/$GAME_ID/players/$SEEKER_ID" \
  -H "Content-Type: application/json" -d '{"role":"seeker"}' | jq_val "['role']"
curl -sf -X PATCH "$BASE/games/$GAME_ID/players/$HIDER_ID" \
  -H "Content-Type: application/json" -d '{"role":"hider"}' | jq_val "['role']"

echo ""
echo "=== POST /games/{id}/start ==="
curl -sf -X POST "$BASE/games/$GAME_ID/start" | jq_val "['status']"

echo ""
echo "=== Forcing transition to seeking (skip hiding timer) ==="
docker compose exec -T postgres psql -U hideandseek -q -c \
  "UPDATE game SET status='seeking', seeking_started_at=NOW() WHERE id='$GAME_ID';"

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

echo ""
echo "=== POST /questions/{id}/answer (hider answers — expect 'no', ~56km apart) ==="
curl -sf -X POST "$BASE/games/$GAME_ID/questions/$Q_ID/answer" \
  -H "X-Client-Id: $HIDER_CLIENT" | pp

STOP_ID="00000000-0000-0000-0000-000000000020"

echo ""
echo "=== GET /candidate-stations (after 1 radar miss — most stops still viable) ==="
CANDS=$(curl -sf "$BASE/games/$GAME_ID/candidate-stations" \
  -H "X-Client-Id: $SEEKER_CLIENT")
CAND_COUNT=$(echo "$CANDS" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))")
echo "  Candidates: $CAND_COUNT (2 expected — Waterloo hiding zone covered by 3km radar miss)"

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
echo "=== POST /questions/matching (hospital category) ==="
Q=$(curl -sf -X POST "$BASE/games/$GAME_ID/questions/matching" \
  -H "Content-Type: application/json" \
  -H "X-Client-Id: $SEEKER_CLIENT" \
  -d '{"location":{"type":"Point","coordinates":[-0.1,51.5]},"category":"hospital"}')
echo "$Q" | pp
Q_ID=$(echo "$Q" | jq_val "['id']")
echo "  Seeker feature: $(echo "$Q" | jq_val "['parameters']['seeker_resolution']['name']")"

echo ""
echo "=== POST /questions/{id}/answer (matching — expect 'no', different hospitals) ==="
curl -sf -X POST "$BASE/games/$GAME_ID/questions/$Q_ID/answer" \
  -H "X-Client-Id: $HIDER_CLIENT" | pp

echo ""
echo "=== POST /questions/measuring (hospital category) ==="
Q=$(curl -sf -X POST "$BASE/games/$GAME_ID/questions/measuring" \
  -H "Content-Type: application/json" \
  -H "X-Client-Id: $SEEKER_CLIENT" \
  -d '{"location":{"type":"Point","coordinates":[-0.1,51.5]},"category":"hospital"}')
echo "$Q" | pp
Q_ID=$(echo "$Q" | jq_val "['id']")

echo ""
echo "=== POST /questions/{id}/answer (measuring — seeker vs hider distance) ==="
curl -sf -X POST "$BASE/games/$GAME_ID/questions/$Q_ID/answer" \
  -H "X-Client-Id: $HIDER_CLIENT" | pp

echo ""
echo "=== GET /questions (all 4 questions) ==="
curl -sf "$BASE/games/$GAME_ID/questions" \
  -H "X-Client-Id: $SEEKER_CLIENT" | pp

echo ""
echo "=== GET /games/{id} (inventory after consuming slots + categories) ==="
curl -sf "$BASE/games/$GAME_ID" | pp

echo ""
echo "=== GET /endgame-exclusions (Victoria station, after_question=0) ==="
ENDGAME=$(curl -sf "$BASE/games/$GAME_ID/endgame-exclusions?station_id=$STOP_ID&after_question=0" \
  -H "X-Client-Id: $SEEKER_CLIENT")
ENTRY_COUNT=$(echo "$ENDGAME" | python3 -c "import sys,json; print(len(json.load(sys.stdin)['entries']))")
echo "  Entries: $ENTRY_COUNT (should be 4 — all answered questions)"
echo "  Hiding zone type: $(echo "$ENDGAME" | jq_val "['hiding_zone']['type']")"

echo ""
echo "=== GET /endgame-exclusions (after_question=2, only questions 3+4) ==="
ENDGAME2=$(curl -sf "$BASE/games/$GAME_ID/endgame-exclusions?station_id=$STOP_ID&after_question=2" \
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
