export const DEFAULT_LAYOUT = [
  "###############",
  "#P....#......G#",
  "#.##..#.###...#",
  "#.....#...#...#",
  "###.#####.#.#.#",
  "#...#.....#.#.#",
  "#.#.#.###.#...#",
  "#.#...#E#...#.#",
  "#.#####.#####.#",
  "#.............#",
  "###############",
];

export const DIRECTIONS = Object.freeze({
  up: { x: 0, y: -1 },
  down: { x: 0, y: 1 },
  left: { x: -1, y: 0 },
  right: { x: 1, y: 0 },
});

const key = ({ x, y }) => `${x},${y}`;
const clonePoint = ({ x, y }) => ({ x, y });

export function parseLayout(layout) {
  if (!Array.isArray(layout) || layout.length < 3) {
    throw new TypeError("layout must contain at least three rows");
  }
  const width = layout[0].length;
  if (width < 3 || layout.some((row) => typeof row !== "string" || row.length !== width)) {
    throw new TypeError("layout rows must be equally sized strings");
  }
  const walls = [];
  const stars = [];
  const shadows = [];
  let player = null;
  let portal = null;

  layout.forEach((row, y) => {
    [...row].forEach((cell, x) => {
      const point = { x, y };
      if (cell === "#") walls.push(point);
      else if (cell === ".") stars.push(point);
      else if (cell === "P") player = point;
      else if (cell === "E") shadows.push(point);
      else if (cell === "G") portal = point;
      else if (cell !== " ") throw new TypeError(`unsupported map cell: ${cell}`);
    });
  });
  if (!player || !portal || shadows.length === 0 || stars.length === 0) {
    throw new TypeError("layout requires P, G, E, and at least one star");
  }
  return { width, height: layout.length, walls, stars, player, portal, shadows };
}

export function createGame(options = {}) {
  const parsed = parseLayout(options.layout ?? DEFAULT_LAYOUT);
  const lives = options.lives ?? 3;
  if (!Number.isInteger(lives) || lives < 1) throw new TypeError("lives must be positive");
  return {
    schemaVersion: 1,
    width: parsed.width,
    height: parsed.height,
    walls: parsed.walls.map(clonePoint),
    stars: parsed.stars.map(clonePoint),
    player: clonePoint(parsed.player),
    playerStart: clonePoint(parsed.player),
    portal: clonePoint(parsed.portal),
    shadows: parsed.shadows.map(clonePoint),
    shadowStarts: parsed.shadows.map(clonePoint),
    score: 0,
    lives,
    turn: 0,
    status: "playing",
    events: [{ type: "game_started", turn: 0 }],
    r5HumanVerification: "pending",
    mergeAuthorized: false,
  };
}

function isWall(state, point) {
  return state.walls.some((wall) => wall.x === point.x && wall.y === point.y);
}

function samePoint(a, b) {
  return a.x === b.x && a.y === b.y;
}

function canEnter(state, point, { shadow = false } = {}) {
  if (point.x < 0 || point.y < 0 || point.x >= state.width || point.y >= state.height) return false;
  if (isWall(state, point)) return false;
  if (!shadow && state.stars.length > 0 && samePoint(point, state.portal)) return false;
  return true;
}

function cloneState(state) {
  return {
    ...state,
    walls: state.walls.map(clonePoint),
    stars: state.stars.map(clonePoint),
    player: clonePoint(state.player),
    playerStart: clonePoint(state.playerStart),
    portal: clonePoint(state.portal),
    shadows: state.shadows.map(clonePoint),
    shadowStarts: state.shadowStarts.map(clonePoint),
    events: state.events.map((event) => ({ ...event })),
  };
}

function appendEvent(state, event) {
  state.events.push({ ...event, turn: state.turn });
  if (state.events.length > 80) state.events.splice(0, state.events.length - 80);
}

function loseLife(state) {
  state.lives -= 1;
  appendEvent(state, { type: "shadow_collision", lives: state.lives });
  if (state.lives === 0) {
    state.status = "lost";
    appendEvent(state, { type: "game_lost", score: state.score });
    return;
  }
  state.player = clonePoint(state.playerStart);
  state.shadows = state.shadowStarts.map(clonePoint);
}

function nextShadowPosition(state, shadow, shadowIndex) {
  const horizontal =
    state.player.x === shadow.x
      ? []
      : [
          {
            x: shadow.x + Math.sign(state.player.x - shadow.x),
            y: shadow.y,
          },
        ];
  const vertical =
    state.player.y === shadow.y
      ? []
      : [
          {
            x: shadow.x,
            y: shadow.y + Math.sign(state.player.y - shadow.y),
          },
        ];
  const candidates =
    (state.turn + shadowIndex) % 2 === 0
      ? [...horizontal, ...vertical]
      : [...vertical, ...horizontal];
  const fallbacks = [
    { x: shadow.x + 1, y: shadow.y },
    { x: shadow.x, y: shadow.y + 1 },
    { x: shadow.x - 1, y: shadow.y },
    { x: shadow.x, y: shadow.y - 1 },
  ];
  return (
    [...candidates, ...fallbacks].find((point) => canEnter(state, point, { shadow: true })) ??
    shadow
  );
}

export function stepGame(current, directionName) {
  if (!Object.hasOwn(DIRECTIONS, directionName))
    throw new TypeError(`invalid direction: ${directionName}`);
  const state = cloneState(current);
  if (state.status !== "playing") return state;
  const direction = DIRECTIONS[directionName];
  const target = { x: state.player.x + direction.x, y: state.player.y + direction.y };
  state.turn += 1;
  if (!canEnter(state, target)) {
    appendEvent(state, { type: "blocked", direction: directionName });
    return state;
  }
  state.player = target;
  appendEvent(state, { type: "player_moved", direction: directionName, position: key(target) });

  const before = state.stars.length;
  state.stars = state.stars.filter((star) => !samePoint(star, state.player));
  if (state.stars.length < before) {
    state.score += 10;
    appendEvent(state, { type: "star_collected", score: state.score });
    if (state.stars.length === 0) appendEvent(state, { type: "portal_opened" });
  }
  if (state.shadows.some((shadow) => samePoint(shadow, state.player))) {
    loseLife(state);
    return state;
  }
  if (state.stars.length === 0 && samePoint(state.player, state.portal)) {
    state.status = "won";
    state.score += Math.max(0, state.lives) * 25;
    appendEvent(state, { type: "game_won", score: state.score });
    return state;
  }

  if (state.turn % 2 === 0) {
    state.shadows = state.shadows.map((shadow, index) => nextShadowPosition(state, shadow, index));
    if (state.shadows.some((shadow) => samePoint(shadow, state.player))) loseLife(state);
  }
  return state;
}

export function auditSnapshot(state) {
  return {
    schemaVersion: state.schemaVersion,
    status: state.status,
    score: state.score,
    lives: state.lives,
    starsRemaining: state.stars.length,
    turns: state.turn,
    eventCount: state.events.length,
    r5HumanVerification: state.r5HumanVerification,
    mergeAuthorized: state.mergeAuthorized,
  };
}
