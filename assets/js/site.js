/* Maří Magdalena — site behaviour.
   No framework, no jQuery. Everything degrades to a working page without JS:
   the lightbox links point at real image files, the filters start unfiltered,
   and revealed elements are visible if the observer never runs. */
(() => {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* An overlay that covers the page has to take the page's tab stops with it.
     Both overlays here are body children, so the rest of the body is the part
     that goes inert — cheaper and less brittle than enumerating focusables,
     and it takes assistive tech with it rather than only the Tab key. Pass the
     elements that must stay live; the drawer keeps the masthead, because the
     burger is its close control. */
  const setInert = (keep, on) => {
    const live = Array.isArray(keep) ? keep : [keep];
    [...document.body.children].forEach((el) => {
      if (live.includes(el) || el.tagName === "SCRIPT") return;
      el.inert = on;
    });
  };

  /* ------------------------------------------------------------ sticky nav */
  /* The gold reading-progress bar that used to be driven from here is gone.
     It is a long-form-article convention on a five-screen site, and it put a
     third moving gold element across the top of a page that already carries a
     gold button and a gold counter. */
  const nav = $("[data-nav]");

  let ticking = false;
  const onScroll = () => {
    if (nav) nav.classList.toggle("is-stuck", window.scrollY > 40);
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
    if (menu && nav) setInert([menu, nav], open);
  };

  burger?.addEventListener("click", () =>
    setMenu(!document.body.classList.contains("is-menu"))
  );
  menu?.addEventListener("click", (e) => {
    if (e.target.closest("a")) setMenu(false);
  });

  /* ----------------------------------------------------------- reel index */
  /* The strip's counter was a hard-coded "01 — 09" printed under a control
     whose whole purpose is to move. Report the leftmost frame actually in
     view, so the readout is worth the line it occupies. */
  const reel = $(".reel");
  const reelIndex = $("[data-reel-index]");

  if (reel && reelIndex) {
    const frames = $$(".reel__item", reel);
    let reelTicking = false;

    const updateReel = () => {
      const edge = reel.scrollLeft + 1;
      let i = frames.findIndex((f) => f.offsetLeft + f.offsetWidth > edge);
      if (i < 0) i = frames.length - 1;
      reelIndex.textContent = String(i + 1).padStart(2, "0");
      reelTicking = false;
    };

    reel.addEventListener(
      "scroll",
      () => {
        if (!reelTicking) {
          reelTicking = true;
          requestAnimationFrame(updateReel);
        }
      },
      { passive: true }
    );
    updateReel();
  }

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

  /* A batched item counts as part of the set even while it is waiting its
     turn to render, so the viewer walks the whole catalogue — all 87 works,
     both chapters — rather than only the tiles currently on screen. Anything
     else has to actually be visible to join the group. */
  function collectLightbox() {
    group = $$("[data-lb-item]").filter(
      (el) =>
        el.matches("[data-batch-item]") || (!el.hidden && el.offsetParent !== null)
    );
  }

  /* ---------------------------------------------------------- batch reveal */
  /* 87 paintings is ~10 000 px of grid and the project archive is 44 000 px.
     The full set stays in the document — so it works without JS, prints, and
     is indexable — but only a batch is displayed at a time. Used by the two
     paintings chapters on /obrazy and by the project archive (items = year
     chapters).

     This used to also run a three-button filter bar over one undivided grid.
     /obrazy is now split into "k prodeji" and "prodáno" as actual sections of
     the page, which is what the filter was standing in for — so the batching
     is just batching, and each chapter counts its own. */
  $$("[data-batch]").forEach((root) => {
    const scope = root.closest("section") || document;
    const items = $$("[data-batch-item]", root);
    const batch = parseInt(root.dataset.batch, 10) || items.length;
    const moreBox = $("[data-more]", scope);
    const moreBtn = $("[data-more-btn]", scope);

    let limit = batch;

    // The button used to be trailed by a live "Zbývá 66 obrazů" in micro-caps.
    // It is still the control's only job to reveal the rest, and the label
    // says so; the residual count was a figure that existed because it could
    // be computed, and it changed under the reader every time they pressed.
    const render = () => {
      items.forEach((i, n) => (i.hidden = n >= limit));
      if (moreBox) moreBox.hidden = items.length - Math.min(limit, items.length) <= 0;
      collectLightbox();
    };

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
    const lbAsk = $("[data-lb-ask]", lb);
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
      // Only paintings carry a sale state, and only unsold ones can be asked
      // about; exhibition and archive images have nothing to enquire after.
      if (lbAsk) {
        const forSale = el.dataset.state === "sale";
        lbAsk.hidden = !forSale;
        if (forSale) {
          const base = lbAsk.getAttribute("href").split("?")[0];
          lbAsk.href = `${base}?subject=${encodeURIComponent(
            "Dotaz k obrazu: " + (el.dataset.title || "")
          )}`;
        }
      }
      // Warm the neighbours so arrowing through feels instant.
      [1, -1].forEach((d) => {
        const n = group[(cursor + d + group.length) % group.length];
        if (n) new Image().src = n.getAttribute("href");
      });
    };

    const open = (i, from) => {
      opener = from;
      lb.hidden = false;
      document.body.classList.add("is-lb");
      show(i);
      /* Everything else goes inert, because the dialog says aria-modal="true"
         and that has to be true of the DOM as well as of the attribute. */
      setInert(lb, true);
      requestAnimationFrame(() => {
        lb.classList.add("is-open");
        /* Focus only once .is-open has landed. .lb is `visibility: hidden`
           until then, and a visibility-hidden element cannot take focus — the
           call used to sit before this frame, so it silently did nothing,
           focus stayed on the thumbnail, and the Tab trap below (which only
           engages when focus is already inside) never engaged either. Twelve
           tabs walked the gallery behind the overlay. */
        $("[data-lb-close]", lb).focus();
      });
    };

    const close = () => {
      lb.classList.remove("is-open");
      document.body.classList.remove("is-lb");
      setTimeout(() => {
        lb.hidden = true;
        lbImg.removeAttribute("src");
      }, 450);
      /* Clear inert before restoring focus: the opener is one of the elements
         that was made inert, and an inert element cannot be focused. */
      setInert(lb, false);
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
        // Trap focus inside the dialog. Links as well as buttons: .lb__ask is
        // an <a>, so collecting only buttons made the viewer's one commercial
        // action unreachable — Tab from the next-chevron wrapped straight back
        // to the close button and skipped it.
        const focusables = $$("button, a[href]", lb).filter(
          (el) => !el.hidden && el.offsetParent !== null
        );
        if (!focusables.length) return;
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
