// Study session: fetch the next card, flip it, send the rating, repeat.
// Keyboard: Space/Enter = show answer, 1-4 = Again/Hard/Good/Easy.
const $ = (id) => document.getElementById(id);
const csrf = document.querySelector('meta[name="csrf-token"]').content;
const deckParam = window.RECALL_DECK ? `?deck=${window.RECALL_DECK}` : "";
let current = null;
let busy = false;

function show(el, on) { $(el).hidden = !on; }

function whenLabel(iso) {
  if (!iso) return "Add more cards or come back tomorrow for new ones.";
  const mins = (new Date(iso) - new Date()) / 60000;
  if (mins < 60) return `Next review in about ${Math.max(1, Math.round(mins))} minutes.`;
  if (mins < 60 * 24) return `Next review in about ${Math.round(mins / 60)} hours.`;
  return `Next review on ${new Date(iso).toLocaleDateString(undefined, { weekday: "long", month: "short", day: "numeric" })}.`;
}

async function next() {
  const res = await fetch(`/api/study/next${deckParam}`);
  if (res.status === 401) { location.href = "/login"; return; }
  const data = await res.json();
  $("due-n").textContent = data.counts.due;
  $("new-n").textContent = data.counts.new;
  if (data.done) {
    current = null;
    show("flashcard", false); show("controls", false); show("done", true);
    $("done-msg").textContent = whenLabel(data.next_due);
    return;
  }
  current = data.card;
  $("deck-tag").textContent = current.is_new ? `${current.deck} · new` : current.deck;
  $("front").textContent = current.front;   // textContent, never innerHTML: card text is user data
  $("back").textContent = current.back;
  for (const [r, label] of Object.entries(data.preview)) $(`p-${r}`).textContent = label;
  show("flashcard", true); show("controls", true); show("done", false);
  show("back", false); show("divider", false); show("ratings", false); show("show", true);
  $("show").focus();
}

function reveal() {
  if (!current) return;
  show("back", true); show("divider", true); show("ratings", true); show("show", false);
}

async function rate(rating) {
  if (!current || busy || $("ratings").hidden) return;
  busy = true;
  try {
    const res = await fetch("/api/study/review", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
      body: JSON.stringify({ card_id: current.id, rating }),
    });
    if (!res.ok) throw new Error((await res.json()).error || "Could not save your answer");
    await next();
  } catch (err) {
    alert(err.message);
  } finally {
    busy = false;
  }
}

$("show").addEventListener("click", reveal);
$("ratings").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) rate(b.dataset.r); });
document.addEventListener("keydown", (e) => {
  if (e.target.matches("input, textarea")) return;
  if ((e.key === " " || e.key === "Enter") && !$("show").hidden) { e.preventDefault(); reveal(); }
  const keys = { 1: "again", 2: "hard", 3: "good", 4: "easy" };
  if (keys[e.key]) rate(keys[e.key]);
});
next();
