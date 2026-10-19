// Small touches for the Guide: starfield, clock, Back key, typewriter text and
// instant index filter.
//
// Design rule: every page already works without this file. The server renders
// all the text, links and filtered lists; this script only makes them nicer.
// That is why each feature first checks its element exists (a page that lacks
// it is skipped) and why nothing here fetches data.

// Everything is wrapped in a function that runs immediately, so its variables
// stay private instead of becoming globals that could clash with other scripts.
(function () {
  // Respect the operating system's "reduce motion" setting: people who get
  // dizzy or distracted by animation get a still page instead.
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;

  // --- Starfield -------------------------------------------------------------
  // Drawn on a <canvas> rather than as 160 HTML elements: one element is much
  // cheaper for the browser to animate.
  const c = document.getElementById("stars");
  if (c) {
    const x = c.getContext("2d");
    let pts = [];
    const size = () => {
      // Size the canvas in device pixels so stars stay sharp on high-DPI screens.
      c.width = innerWidth * devicePixelRatio; c.height = innerHeight * devicePixelRatio;
      // Each star: position, radius and a random phase (t) so they twinkle out of step.
      pts = Array.from({ length: 160 }, () => ({ x: Math.random() * c.width, y: Math.random() * c.height, r: Math.random() * 1.4 + .2, t: Math.random() * 6 }));
    };
    const draw = ts => {
      x.clearRect(0, 0, c.width, c.height);
      for (const p of pts) {
        // A sine wave over time gives each star a slow, smooth twinkle.
        x.globalAlpha = reduce ? .7 : .45 + .45 * Math.sin(ts / 900 + p.t);
        x.fillStyle = "#f6e7c8"; x.beginPath(); x.arc(p.x, p.y, p.r * devicePixelRatio, 0, 7); x.fill();
      }
      // requestAnimationFrame runs once per screen refresh and pauses in
      // background tabs, unlike setInterval. With reduced motion, draw once only.
      if (!reduce) requestAnimationFrame(draw);
    };
    addEventListener("resize", () => { size(); if (reduce) draw(0); });
    size(); requestAnimationFrame(draw);
  }

  // --- Clock -----------------------------------------------------------------
  // Galactic Standard Time, more or less (it is your local time).
  const clock = document.getElementById("clock");
  if (clock) {
    const tick = () => { clock.textContent = "GST " + new Date().toTimeString().slice(0, 8); };
    tick(); setInterval(tick, 1000);
  }

  // --- Back key --------------------------------------------------------------
  // A plain link cannot go "back", so this key is a button that uses the
  // browser history. If the Guide was opened in a fresh tab there is no
  // history, so fall back to the index instead of doing nothing.
  const back = document.getElementById("kBack");
  if (back) back.addEventListener("click", () => history.length > 1 ? history.back() : location.assign("/index"));

  // --- Typewriter text -------------------------------------------------------
  // The full entry text is already in the page (good for search engines,
  // screen readers and people without JavaScript). Here it is hidden and
  // "typed" back in, three characters every 14 ms.
  //
  // Paragraphs can contain cross-reference links. Typing works on plain text
  // (textContent), which would lose the links, so the original HTML of each
  // paragraph is saved first and put back once that paragraph finishes.
  const body = document.querySelector(".body[data-type]");
  if (body && !reduce) {
    const paras = [...body.querySelectorAll("p")];
    const html = paras.map(p => p.innerHTML);    // with links, restored at the end
    const texts = paras.map(p => p.textContent); // plain text, used while typing
    paras.forEach(p => { p.textContent = ""; });
    const cur = document.createElement("span"); cur.className = "cursor";
    let pi = 0, ci = 0; // paragraph index, character index
    // finish() shows everything at once: used when typing ends or on a click.
    const finish = () => { clearInterval(timer); cur.remove(); paras.forEach((p, i) => { p.innerHTML = html[i]; }); };
    const timer = setInterval(() => {
      if (pi >= paras.length) { finish(); return; }
      ci = Math.min(texts[pi].length, ci + 3);
      paras[pi].textContent = texts[pi].slice(0, ci); paras[pi].append(cur);
      if (ci >= texts[pi].length) { paras[pi].innerHTML = html[pi]; pi++; ci = 0; }
    }, 14);
    // Click the text to skip the animation. { once: true } removes the
    // listener after the first click, so later clicks on links behave normally.
    body.addEventListener("click", finish, { once: true });
  }

  // --- Instant index filter --------------------------------------------------
  // Without JavaScript the filter box is a normal form: pressing Enter asks the
  // server for a filtered page. With JavaScript, the list narrows as you type.
  // Each <li> carries its name and summary in lower case in data-text (written
  // by the template), so matching is a simple, fast "includes" check.
  const filter = document.getElementById("filter");
  const list = document.getElementById("refs");
  if (filter && list) {
    const items = [...list.querySelectorAll("li[data-text]")];
    const empty = document.getElementById("empty");
    const count = document.getElementById("count");
    filter.addEventListener("input", () => {
      const q = filter.value.trim().toLowerCase();
      let shown = 0;
      // Toggling the hidden attribute is cheaper than rebuilding the list.
      for (const li of items) { const hit = !q || li.dataset.text.includes(q); li.hidden = !hit; if (hit) shown++; }
      if (empty) empty.hidden = shown > 0;
      if (count) count.textContent = shown;
    });
  }
})();
