import { auditSnapshot, createGame, stepGame } from "./game-core.js";

const canvas = document.querySelector("#game");
const context = canvas.getContext("2d");
const scoreNode = document.querySelector("#score");
const livesNode = document.querySelector("#lives");
const starsNode = document.querySelector("#stars");
const statusNode = document.querySelector("#status");
const auditNode = document.querySelector("#audit-json");
const restartButton = document.querySelector("#restart");
let game = createGame();

function drawPixelSprite(x, y, cell, color, eyeColor = "#eafcff") {
  const padding = Math.max(2, Math.floor(cell * 0.18));
  const size = cell - padding * 2;
  context.fillStyle = color;
  context.fillRect(x + padding, y + padding, size, size);
  context.fillStyle = eyeColor;
  context.fillRect(
    x + padding + Math.floor(size * 0.2),
    y + padding + Math.floor(size * 0.22),
    Math.max(2, Math.floor(size * 0.18)),
    Math.max(2, Math.floor(size * 0.18)),
  );
  context.fillRect(
    x + padding + Math.floor(size * 0.62),
    y + padding + Math.floor(size * 0.22),
    Math.max(2, Math.floor(size * 0.18)),
    Math.max(2, Math.floor(size * 0.18)),
  );
}

function render() {
  const availableWidth = Math.min(760, Math.max(280, canvas.parentElement.clientWidth - 2));
  const cell = Math.max(18, Math.floor(availableWidth / game.width));
  canvas.width = cell * game.width;
  canvas.height = cell * game.height;
  context.fillStyle = "#071323";
  context.fillRect(0, 0, canvas.width, canvas.height);

  game.walls.forEach(({ x, y }) => {
    context.fillStyle = "#173b67";
    context.fillRect(x * cell + 1, y * cell + 1, cell - 2, cell - 2);
    context.fillStyle = "#2867a8";
    context.fillRect(x * cell + 4, y * cell + 4, cell - 8, 3);
  });
  game.stars.forEach(({ x, y }) => {
    const cx = x * cell + cell / 2;
    const cy = y * cell + cell / 2;
    const radius = Math.max(3, cell * 0.16);
    context.fillStyle = "#ffd166";
    context.beginPath();
    context.moveTo(cx, cy - radius);
    context.lineTo(cx + radius, cy);
    context.lineTo(cx, cy + radius);
    context.lineTo(cx - radius, cy);
    context.closePath();
    context.fill();
  });
  const portalOpen = game.stars.length === 0;
  context.strokeStyle = portalOpen ? "#64ffda" : "#5b6880";
  context.lineWidth = Math.max(2, cell * 0.12);
  context.strokeRect(game.portal.x * cell + 6, game.portal.y * cell + 6, cell - 12, cell - 12);
  game.shadows.forEach(({ x, y }) => {
    drawPixelSprite(x * cell, y * cell, cell, "#9b5de5");
  });
  drawPixelSprite(game.player.x * cell, game.player.y * cell, cell, "#2ee6a6", "#081522");

  scoreNode.textContent = String(game.score);
  livesNode.textContent = "◆".repeat(game.lives) || "—";
  starsNode.textContent = String(game.stars.length);
  statusNode.textContent =
    game.status === "won"
      ? "星門已開，你帶著光回家了！"
      : game.status === "lost"
        ? "影子吞沒了星光。按 R 再試一次。"
        : portalOpen
          ? "星門已開，前往青色出口！"
          : "收集全部星光，避開紫色影子。";
  statusNode.dataset.state = game.status;
  auditNode.textContent = JSON.stringify(auditSnapshot(game), null, 2);
}

function move(direction) {
  game = stepGame(game, direction);
  render();
}

function restart() {
  game = createGame();
  render();
  canvas.focus();
}

const keyMap = {
  ArrowUp: "up",
  w: "up",
  W: "up",
  ArrowDown: "down",
  s: "down",
  S: "down",
  ArrowLeft: "left",
  a: "left",
  A: "left",
  ArrowRight: "right",
  d: "right",
  D: "right",
};

window.addEventListener("keydown", (event) => {
  if (keyMap[event.key]) {
    event.preventDefault();
    move(keyMap[event.key]);
  } else if (event.key === "r" || event.key === "R" || event.key === "Enter") {
    restart();
  }
});
document.querySelectorAll("[data-direction]").forEach((button) => {
  button.addEventListener("click", () => move(button.dataset.direction));
});
restartButton.addEventListener("click", restart);
window.addEventListener("resize", render);
render();
