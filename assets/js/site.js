/* Maří Magdalena — site behaviour.
   No framework, no jQuery. Everything degrades to a working page without JS:
   the lightbox links point at real image files, the filters start unfiltered,
   and revealed elements are visible if the observer never runs. */
(() => {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ------------------------------------------------------ scroll progress */
  const progress = $("[data-progress]");
  const nav = $("[data-nav]");

  let ticking = false;
  const onScroll = () => {
    const y = window.scrollY;
    if (progress) {
      const max = document.documentElement.scrollHeight - innerHeight;
      progress.style.transform = `scaleX(${max > 0 ? y / max : 0})`;
    }
    if (nav) nav.classList.toggle("is-stuck", y > 40);
    ticking = false;
  };

  addEventListener(
    "scroll",
    () => {
      if (!ticking) {
        ticking = true;
        requestAnimationFrame(onScroll);
      }
    },
    { passive: true }
  );
  onScroll();

  /* ---------------------------------------------------------- mobile menu */
  const burger = $("[data-burger]");
  const menu = $("[data-menu]");

  const setMenu = (open) => {
    document.body.classList.toggle("is-menu", open);
    burger?.setAttribute("aria-expanded", String(open));
  };

  burger?.addEventListener("click", () =>
    setMenu(!document.body.classList.contains("is-menu"))
  );
  menu?.addEventListener("click", (e) => {
    if (e.target.closest("a")) setMenu(false);
  });

  /* -------------------------------------------------------------- reveals */
  /* `observe` is exported to the batching code below: an element that was
     display:none when the observer first ran never reports an intersection,
     so anything revealed later has to be handed back in. */
  let observeReveals;

  if (reduced || !("IntersectionObserver" in window)) {
    observeReveals = (scope = document) =>
      $$(".rv, .rv-clip", scope).forEach((el) => el.classList.add("is-in"));
  } else {
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          entry.target.classList.add("is-in");
          io.unobserve(entry.target);
        });
      },
      { rootMargin: "0px 0px -8% 0px", threshold: 0.06 }
    );
    observeReveals = (scope = document) => {
      const list = $$(".rv, .rv-clip", scope);
      if (scope !== document && scope.matches?.(".rv, .rv-clip")) list.push(scope);
      list.forEach((el) => {
        if (!el.classList.contains("is-in")) io.observe(el);
      });
    };
  }

  observeReveals();

  /* ------------------------------------------------------------- lightbox */
  const lb = $("[data-lb]");
  let group = [];
  let cursor = 0;
  let opener = null;

  // Set by a batched list so the viewer can page through everything that
  // matches the current filter, not just the tiles rendered so far.
  let groupOverride = null;

  function collectLightbox() {
    group = groupOverride
      ? groupOverride.filter((el) => el.matches("[data-lb-item]"))
      : $$("[data-lb-item]").filter((el) => !el.hidden && el.offsetParent !== null);
  }

  /* ------------------------------------------------- filter + batch reveal */
  /* 87 paintings is ~10 000 px of grid and the project archive is 44 000 px.
     The full set stays in the document — so it works without JS, prints, and
     is indexable — but only a batch is displayed at a time. Filtering and
     batching share one render pass, because "show more" has to mean more of
     the *current* filter. Used by the paintings grid (items = tiles, with
     filters) and the project archive (items = year chapters, no filters). */
  $$("[data-batch]").forEach((root) => {
    const scope = root.closest("section") || document;
    const items = $$("[data-batch-item]", root);
    const batch = parseInt(root.dataset.batch, 10) || items.length;
    const filterBar = $("[data-filters]", scope);
    const countEl = $("[data-filter-count]", scope);
    const moreBox = $("[data-more]", scope);
    const moreBtn = $("[data-more-btn]", scope);
    const moreCount = $("[data-more-count]", scope);
    const noun = root.dataset.batchNoun || "";

    let mode = "all";
    let limit = batch;

    const render = () => {
      const matching = items.filter(
        (i) => mode === "all" || i.dataset.state === mode
      );
      items.forEach((i) => (i.hidden = true));
      matching.slice(0, limit).forEach((i) => (i.hidden = false));

      const shown = Math.min(limit, matching.length);
      if (countEl) countEl.textContent = `${shown} z ${matching.length}`;
      // The viewer browses the whole filtered set even though only `limit`
      // tiles are on screen.
      if (matching.some((i) => i.matches("[data-lb-item]"))) groupOverride = matching;
      if (moreBox) {
        const rest = matching.length - shown;
        moreBox.hidden = rest <= 0;
        if (moreCount) moreCount.textContent = `Zbývá ${rest}${noun ? " " + noun : ""}`;
      }
      collectLightbox();
    };

    filterBar?.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-filter]");
      if (!btn) return;
      $$("[data-filter]", filterBar).forEach((b) =>
        b.classList.toggle("is-on", b === btn)
      );
      mode = btn.dataset.filter;
      limit = batch;
      render();
    });

    moreBtn?.addEventListener("click", () => {
      const before = new Set(items.filter((i) => !i.hidden));
      limit += batch;
      render();
      // Newly shown items were display:none when the observer first ran, so
      // hand them back to it — and reveal the first screenful immediately,
      // since the user asked for them and won't scroll up to trigger them.
      items
        .filter((i) => !i.hidden && !before.has(i))
        .forEach((item, index) => {
          observeReveals(item);
          if (index === 0) {
            item.classList.add("is-in");
            $$(".rv, .rv-clip", item).forEach((el) => el.classList.add("is-in"));
          }
        });
    });

    render();
  });

  if (lb) {
    const lbImg = $("[data-lb-img]", lb);
    const lbTitle = $("[data-lb-title]", lb);
    const lbTag = $("[data-lb-tag]", lb);
    const lbCount = $("[data-lb-count]", lb);
    const pad = (n) => String(n).padStart(2, "0");

    const show = (i) => {
      if (!group.length) return;
      cursor = (i + group.length) % group.length;
      const el = group[cursor];
      lbImg.classList.remove("is-ready");
      const next = new Image();
      next.onload = () => {
        lbImg.src = next.src;
        lbImg.alt = el.dataset.title || "";
        lbImg.classList.add("is-ready");
      };
      next.src = el.getAttribute("href");
      lbTitle.textContent = el.dataset.title || "";
      lbTag.textContent = el.dataset.tag || "";
      lbCount.textContent = `${pad(cursor + 1)} / ${pad(group.length)}`;
      // Warm the neighbours so arrowing through feels instant.
      [1, -1].forEach((d) => {
        const n = group[(cursor + d + group.length) % group.length];
        if (n) new Image().src = n.getAttribute("href");
      });
    };

    const open = (i, from) => {
      opener = from;
      lb.hidden = false;
      requestAnimationFrame(() => lb.classList.add("is-open"));
      document.body.classList.add("is-lb");
      show(i);
      $("[data-lb-close]", lb).focus();
    };

    const close = () => {
      lb.classList.remove("is-open");
      document.body.classList.remove("is-lb");
      setTimeout(() => {
        lb.hidden = true;
        lbImg.removeAttribute("src");
      }, 450);
      opener?.focus();
      opener = null;
    };

    document.addEventListener("click", (e) => {
      const item = e.target.closest("[data-lb-item]");
      if (!item) return;
      e.preventDefault();
      collectLightbox();
      const i = group.indexOf(item);
      open(i < 0 ? 0 : i, item);
    });

    $("[data-lb-close]", lb).addEventListener("click", close);
    $("[data-lb-prev]", lb).addEventListener("click", () => show(cursor - 1));
    $("[data-lb-next]", lb).addEventListener("click", () => show(cursor + 1));
    $(".lb__stage", lb).addEventListener("click", (e) => {
      if (e.target === e.currentTarget) close();
    });

    addEventListener("keydown", (e) => {
      if (document.body.classList.contains("is-menu") && e.key === "Escape") {
        setMenu(false);
        return;
      }
      if (lb.hidden) return;
      if (e.key === "Escape") close();
      else if (e.key === "ArrowLeft") show(cursor - 1);
      else if (e.key === "ArrowRight") show(cursor + 1);
      else if (e.key === "Tab") {
        // Trap focus inside the dialog.
        const focusables = $$("button", lb);
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    });

    let touchX = null;
    lb.addEventListener("touchstart", (e) => (touchX = e.changedTouches[0].clientX), {
      passive: true,
    });
    lb.addEventListener(
      "touchend",
      (e) => {
        if (touchX === null) return;
        const dx = e.changedTouches[0].clientX - touchX;
        if (Math.abs(dx) > 55) show(cursor + (dx < 0 ? 1 : -1));
        touchX = null;
      },
      { passive: true }
    );

    collectLightbox();
  }

  /* ---------------------------------------------------------- deferred map */
  /* Google's embed is only inserted once someone asks for it, so the footer
     never ships an empty bordered box and no third-party cookie is set on a
     visitor who never looks at the map. */
  const mapSlot = $("[data-map]");
  mapSlot?.addEventListener("click", (e) => {
    if (!e.target.closest("[data-map-load]")) return;
    const frame = document.createElement("iframe");
    frame.src = mapSlot.dataset.src;
    frame.title = mapSlot.dataset.title;
    frame.loading = "lazy";
    frame.referrerPolicy = "no-referrer-when-downgrade";
    mapSlot.replaceChildren(frame);
  });

  /* ------------------------------------------------ hover plate for index */
  const peek = $("[data-peek]");
  const scope = $("[data-peek-scope]");
  const finePointer = matchMedia("(hover: hover) and (pointer: fine)").matches;

  if (peek && scope && finePointer && !reduced) {
    const peekImg = $("img", peek);
    const target = { x: 0, y: 0 };
    const at = { x: 0, y: 0 };
    let active = false;
    let raf = null;

    const loop = () => {
      at.x += (target.x - at.x) * 0.13;
      at.y += (target.y - at.y) * 0.13;
      peek.style.transform = `translate(${at.x}px, ${at.y}px) translate(-50%, -50%) scale(${
        active ? 1 : 0.94
      })`;
      raf = active || Math.abs(target.x - at.x) > 0.5 ? requestAnimationFrame(loop) : null;
    };

    scope.addEventListener("pointermove", (e) => {
      const row = e.target.closest("[data-peek-src]");
      target.x = e.clientX;
      target.y = e.clientY;

      if (row) {
        const src = row.dataset.peekSrc;
        if (peekImg.dataset.src !== src) {
          peekImg.dataset.src = src;
          peekImg.src = src;
          // Posters and photographs sit side by side in this list, so the
          // preview takes each item's own proportions rather than cropping.
          if (row.dataset.peekRatio) peek.style.aspectRatio = row.dataset.peekRatio;
        }
        if (!active) {
          at.x = target.x;
          at.y = target.y;
          active = true;
          peek.classList.add("is-on");
        }
      } else if (active) {
        active = false;
        peek.classList.remove("is-on");
      }
      if (!raf) raf = requestAnimationFrame(loop);
    });

    scope.addEventListener("pointerleave", () => {
      active = false;
      peek.classList.remove("is-on");
    });
  }
})();
