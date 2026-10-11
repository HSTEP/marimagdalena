/* Maří Magdalena — site behaviour.
   No framework, no jQuery. Everything degrades to a working page without JS:
   the lightbox links point at real image files, the filters start unfiltered,
   and revealed elements are visible if the observer never runs. */
(() => {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* iOS paints :active only under an element with a touch listener, so
     without one the pressed states in site.css never showed on an iPhone,
     and a tap on a painting got no answer until the lightbox arrived. */
  document.addEventListener("touchstart", () => {}, { passive: true });

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

  /* The drawer belongs to the burger, and past 960 there is no burger — the
     media query that declares it stops applying. A drawer opened on a phone
     and then carried past the rung (rotating a tablet, dragging a desktop
     window wider, a browser leaving a split view) became a full-screen ink
     panel whose only close control had been removed from the page. Measured:
     opened at 390 then resized to 1024, 1440 and 1920 leaves visibility
     visible, clip-path inset(0px), burger display none and body overflow
     hidden. Escape still closed it and the desktop links sat above it at
     z-index 50, so it was degraded rather than sealed — but a panel with no
     visible exit is not a state worth leaving reachable. Same 960 as the CSS,
     read from the same kind of query rather than restated as a number here —
     in em, like the masthead's rungs, and in the min/max syntax older iPhones
     read (site.css). */
  matchMedia("not all and (max-width: 60em)").addEventListener("change", (e) => {
    if (e.matches) setMenu(false);
  });

  /* ----------------------------------------------------------- reel index */
  /* The strip's counter was a hard-coded "01 — 09" printed under a control
     whose whole purpose is to move. Report the frame the reader is looking at,
     so the readout is worth the line it occupies.

     This compared two numbers measured from different origins. `.reel` is
     `position: static`, so a plate's `offsetParent` is `body.home` and
     `offsetLeft` is the distance from the page's left edge; `scrollLeft` is
     the distance from the strip's own padding box. Testing
     `offsetLeft + offsetWidth > scrollLeft` therefore overstates every plate's
     position by `frames[0].offsetLeft` — 20px at 390, 51 at 1024, 72 at 1440,
     208 at 1920, 496 at 2560 — and picks the plate one place too early
     wherever that displacement exceeds the gap, which it does at every width.
     Measured at five rest positions across eleven widths, the readout named a
     plate that was not on screen in 42 of 55 of them; it was right at
     `scrollLeft: 0` and essentially nowhere else, which is to say it was right
     until the reader touched the thing it describes. At 1440 dragged to the
     end the strip shows plates 7, 8 and 9 and the counter read "06".

     Read in viewport coordinates instead, against the strip's content box.
     That box is the viewing region `scroll-padding-inline-end` already
     declares in the stylesheet (sec. 9), so the counter and the keyboard now
     agree about where the strip begins and ends.

     The plate holding most of that region, ties to the leftmost — not the
     leftmost plate with any ink in it. The two agree everywhere except the
     last rest position below 620, where the strip cannot scroll far enough to
     bring plate 9 to the start: plate 9 fills the screen, plate 8 hangs on as
     a 30px sliver at the left, and "leftmost in view" names the sliver. The
     ties clause is what keeps the desktop honest, where three whole plates are
     equally in view and the first of them is the answer.

     So the ceiling is deliberate and varies with how much is on screen: the
     counter reaches 09 at or below 620, 08 from 700 to 960, and 07 at 1024 and
     up, where reaching the end means plates 7, 8 and 9 are all in view at
     once. "07 / 09" under a strip showing the last three of nine is a position,
     not a shortfall.

     Recomputed on resize as well as on scroll: both the plate count and the
     browser's own correction to `scrollLeft` change with the width. */
  const reel = $(".reel");
  const reelIndex = $("[data-reel-index]");
  const frames = reel ? $$(".reel__item", reel) : [];

  if (reel && reelIndex && frames.length) {
    let reelTicking = false;

    const updateReel = () => {
      reelTicking = false;
      const box = reel.getBoundingClientRect();
      const cs = getComputedStyle(reel);
      const left = box.left + reel.clientLeft + parseFloat(cs.paddingLeft);
      const right = left + reel.clientWidth - parseFloat(cs.paddingLeft)
        - parseFloat(cs.paddingRight);

      let best = 0;
      let widest = -1;
      frames.forEach((f, i) => {
        const b = f.getBoundingClientRect();
        const shown = Math.min(b.right, right) - Math.max(b.left, left);
        if (shown > widest + 0.5) {
          best = i;
          widest = shown;
        }
      });
      reelIndex.textContent = String(best + 1).padStart(2, "0");
    };

    const tickReel = () => {
      if (reelTicking) return;
      reelTicking = true;
      requestAnimationFrame(updateReel);
    };

    /* A strip that holds no more than it shows has nothing to drag: no hand
       cursor, no "drag sideways". The owner decides how many works it holds. */
    const reelMeta = $("[data-reel-meta]");
    const markStatic = () => {
      const still = reel.scrollWidth <= reel.clientWidth + 1;
      reel.classList.toggle("is-static", still);
      reelMeta?.classList.toggle("is-static", still);
    };
    markStatic();
    addEventListener("resize", markStatic, { passive: true });

    reel.addEventListener("scroll", tickReel, { passive: true });
    addEventListener("resize", tickReel, { passive: true });
    updateReel();

    /* A mouse can drag the strip. A wheel scrolls the page, not the reel,
       and dragging a plate started the browser's own link drag, so with a
       mouse six of the nine works were reachable only by a hairline
       scrollbar. Past 6px of travel the strip follows the pointer with snap
       off, the click that ends a drag opens nothing, and on release it eases
       to the nearest plate. Touch keeps the browser's native swipe. */
    let drag = null;
    let dragged = false;
    const startEdge = () => {
      const box = reel.getBoundingClientRect();
      return box.left + reel.clientLeft + parseFloat(getComputedStyle(reel).paddingLeft);
    };
    reel.addEventListener("pointerdown", (e) => {
      dragged = false;
      if (e.pointerType !== "mouse" || e.button !== 0) return;
      drag = { id: e.pointerId, x: e.clientX, left: reel.scrollLeft, moved: false };
    });
    reel.addEventListener("pointermove", (e) => {
      if (!drag || e.pointerId !== drag.id) return;
      const dx = e.clientX - drag.x;
      if (!drag.moved) {
        if (Math.abs(dx) < 6) return;
        drag.moved = true;
        reel.setPointerCapture(e.pointerId);
        reel.classList.add("is-dragging");
      }
      reel.scrollLeft = drag.left - dx;
    });
    const endDrag = () => {
      if (!drag) return;
      const { moved, left } = drag;
      drag = null;
      if (!moved) return;
      dragged = true;
      const edge = startEdge();
      // Nearest plate, leaning one plate in the direction of a deliberate pull.
      const travel = reel.scrollLeft - left;
      let target = frames[0];
      let best = Infinity;
      frames.forEach((f) => {
        const off = f.getBoundingClientRect().left - edge - Math.sign(travel) * 40;
        if (Math.abs(off) < best) {
          best = Math.abs(off);
          target = f;
        }
      });
      reel.classList.remove("is-dragging");
      reel.scrollTo({
        left: reel.scrollLeft + target.getBoundingClientRect().left - edge,
        behavior: reduced ? "auto" : "smooth",
      });
    };
    /* Tab forward brings each plate in whole; Shift+Tab back from below the
       strip landed on plate 9 with 16% of it on screen at 390, because the
       browser only scrolls a focused element until some of it shows. A plate
       that takes focus while starting left of the viewing region is brought
       to its start. */
    reel.addEventListener("focusin", (e) => {
      const plate = e.target.closest(".reel__item");
      if (!plate) return;
      const off = plate.getBoundingClientRect().left - startEdge();
      if (off < -1) reel.scrollBy({ left: off, behavior: reduced ? "auto" : "smooth" });
    });
    reel.addEventListener("pointerup", endDrag);
    reel.addEventListener("pointercancel", endDrag);
    reel.addEventListener("dragstart", (e) => e.preventDefault());
    reel.addEventListener(
      "click",
      (e) => {
        if (!dragged) return;
        dragged = false;
        e.preventDefault();
        e.stopPropagation();
      },
      true
    );
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
    /* A reveal is a courtesy to content arriving at the edge of the screen,
       and it must never be the reason content is missing. The observer used
       to wait for 6% of an element to be 8% inside the bottom edge, so a band
       of 80-150px at the foot of every resting screen stayed blank until the
       next scroll, and a flick on a phone ran 42-63% of the screen blank while
       the wipes caught up. It now starts a tenth of a screen early, on the
       first pixel.
       Anything first seen already well inside the screen — a flick, an anchor
       jump, a restored scroll position, a "show more" — is simply shown. And
       grid items take their stagger from the order they arrive in together,
       capped at three steps, instead of their position in the markup: the
       paintings wall staggered by `index % 12`, a sawtooth that had nothing to
       do with which row was coming into view, and its last tiles waited 275ms
       for no reason the reader could see. */
    const GRID = ".works__item, .tiles__item, .xcat__item, .arch__item, .person, .reel, .grid > a.rv";
    const io = new IntersectionObserver(
      (entries) => {
        let step = 0;
        entries
          .filter((entry) => entry.isIntersecting)
          .sort(
            (a, b) =>
              a.boundingClientRect.top - b.boundingClientRect.top ||
              a.boundingClientRect.left - b.boundingClientRect.left
          )
          .forEach((entry) => {
            const el = entry.target;
            io.unobserve(el);
            if (entry.boundingClientRect.top < innerHeight * 0.6) {
              el.classList.add("is-now");
            } else if (el.matches(GRID)) {
              el.style.setProperty("--stagger", `${Math.min(step++, 3) * 70}ms`);
            }
            el.classList.add("is-in");
          });
      },
      { rootMargin: "0px 0px 10% 0px", threshold: 0 }
    );
    /* Focus is a reader asking for that control now. Tabbing onto "Objednat
       se" on /cenik used to put the ring on a button still at a fraction of
       its opacity for ~0.4s, and the ring fades with what it surrounds. */
    document.addEventListener("focusin", (e) => {
      for (let el = e.target; el && el !== document.body; el = el.parentElement) {
        if (el.matches(".rv, .rv-clip") && !el.classList.contains("is-in")) {
          io.unobserve(el);
          el.classList.add("is-now", "is-in");
        }
      }
    });

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
  /* close() cannot finish its own work synchronously: the dialog fades for
     0.45s and only then may it be hidden and its src dropped. That pending
     teardown has to be cancellable, because the reader can be back inside the
     window before it fires. See open() and close() below. */
  let closeTimer = null;

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
      const fresh = items.filter((i) => !i.hidden && !before.has(i));
      fresh.forEach((item, index) => {
        observeReveals(item);
        if (index === 0) {
          item.classList.add("is-in");
          $$(".rv, .rv-clip", item).forEach((el) => el.classList.add("is-in"));
        }
      });
      /* Focus goes to the first thing the press revealed. On /obrazy the
         button hides itself once the chapter is complete, and focus fell to
         BODY: the next Tab skipped all eighteen new works for sale. On
         /projekty the new years appear above a button that stays, so the
         next Tab went to the footer. A painting is a link and takes focus as
         it is; a chapter is focused at its year heading. */
      const first = fresh[0];
      const target = first && (first.matches("a[href], button") ? first
        : $("h2, h3, h4", first) || first);
      if (target) {
        if (!target.matches("a[href], button")) target.tabIndex = -1;
        target.focus();
      }
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

    /* Two plates on one stage, and nothing on the screen changes until the
       next picture is decoded. The viewer used to set the new title, counter
       and enquiry at once, fade the old picture to black and load the new one
       into the same element — so on a phone network the stage sat black for
       most of a second under a title it did not show yet, and then the
       *previous* painting faded back in under the new title before being
       replaced: "Napsat o tomto obraze" under the wrong work, at the one
       moment the site is selling. Now the incoming plate is decoded behind
       the current one and crossfades over it, and the words change in the
       same frame as the picture. A step that is overtaken by a newer one is
       dropped. If the target's own tile has already loaded, its file goes up
       at once and the full-size image replaces it when ready, so a tap is
       answered immediately. */
    const lbBack = lbImg.cloneNode();
    lbBack.removeAttribute("data-lb-img");
    /* The plate behind is never the work being shown, so it is never read:
       with both exposed, the dialog named the outgoing painting and the
       incoming one side by side, the stale one first about half the time. */
    lbBack.setAttribute("aria-hidden", "true");
    lbImg.after(lbBack);
    let front = lbImg;
    let back = lbBack;
    let request = 0;
    let settle = null;

    /* The title is a live region, and a step can write it twice — the tile's
       file first, then the full one — so text is only set when it changes,
       and each work is announced once. */
    const put = (node, text) => {
      if (node.textContent !== text) node.textContent = text;
    };
    const label = (el) => {
      put(lbTitle, el.dataset.title || "");
      put(lbTag, el.dataset.tag || "");
      put(lbCount, `${pad(cursor + 1)} / ${pad(group.length)}`);
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
    };

    // Put `src` up as the front plate once it can be painted whole.
    const present = (src, el, token, onShown) => {
      const plate = back;
      plate.classList.remove("is-ready");
      plate.src = src;
      plate.alt = el.dataset.title || "";
      const swap = () => {
        if (token !== request) return;
        back = front;
        front = plate;
        front.style.zIndex = "2";
        back.style.zIndex = "1";
        front.removeAttribute("aria-hidden");
        back.setAttribute("aria-hidden", "true");
        label(el);
        front.classList.add("is-ready");
        // A dissolve, both ways at once: pictures of different proportions
        // must not show the outgoing one's edges around the incoming one.
        // The outgoing plate is reused only once its fade has finished — a
        // plate given a new src while still visible goes blank.
        back.classList.remove("is-ready");
        clearTimeout(settle);
        settle = setTimeout(() => onShown?.(), 320);
      };
      plate.decode().then(swap, swap);
    };

    const show = (i) => {
      if (!group.length) return;
      cursor = (i + group.length) % group.length;
      const el = group[cursor];
      const token = ++request;
      const full = el.getAttribute("href");
      const tile = el.querySelector("img");
      const quick = tile && tile.complete && tile.naturalWidth && tile.currentSrc;
      if (quick && quick !== full) {
        present(quick, el, token, () => present(full, el, token));
      } else {
        present(full, el, token);
      }
      [1, -1].forEach((d) => {
        const n = group[(cursor + d + group.length) % group.length];
        if (n) new Image().src = n.getAttribute("href");
      });
    };

    const open = (i, from) => {
      /* First, and before anything reads or writes lb.hidden. A close still
         inside its 0.45s fade has a teardown booked that sets lb.hidden = true
         and strips the image src; nothing used to cancel it, so reopening
         inside that window let the timer dismantle a dialog that was now open.
         What the reader was left with was not a closed lightbox: the page
         stayed under `body.is-lb` with `overflow: hidden`, all five children of
         <body> still inert from setInert() below, and the dialog itself
         display:none — 0 focusable controls, no scrolling, and Escape bailing
         at `if (lb.hidden) return`. Dead until reload. Measured on the keyboard
         path (Enter, Escape, Enter with a 3.7ms gap) on /galerie and /obrazy;
         reproduced at every reopen delay up to ~450ms and clean from 460ms.
         The gesture is "close — no, wait": Escape restores focus to the opener,
         so the very next Enter reopens, and there is no 450ms in a human hand. */
      clearTimeout(closeTimer);
      closeTimer = null;
      opener = from;
      lb.hidden = false;
      document.body.classList.add("is-lb");
      show(i);
      /* Everything else goes inert, because the dialog says aria-modal="true"
         and that has to be true of the DOM as well as of the attribute. */
      setInert(lb, true);
      requestAnimationFrame(() => {
        lb.classList.add("is-open");
        /* Focus once .is-open has landed — a visibility-hidden element cannot
           take focus, and before this frame existed the call silently did
           nothing: focus stayed on the thumbnail, the Tab trap below (which
           only engages when focus is already inside) never engaged, and twelve
           tabs walked the gallery behind the overlay.

           The frame alone is not enough, and this comment used to claim it
           was. `visibility` was in .lb's transition, so it stayed `hidden` for
           0.45s after the class landed and the call kept no-opping for anyone
           not on prefers-reduced-motion. What makes the line below work is
           .lb.is-open dropping visibility from the transition (site.css,
           sec. 20) — keep the two together. */
        $("[data-lb-close]", lb).focus();
      });
    };

    const close = () => {
      lb.classList.remove("is-open");
      document.body.classList.remove("is-lb");
      /* Kept in a handle so open() can cancel it, and cleared here too so a
         second close cannot leave two bookings against one dialog. */
      clearTimeout(closeTimer);
      closeTimer = setTimeout(() => {
        closeTimer = null;
        lb.hidden = true;
        [front, back].forEach((plate) => {
          plate.classList.remove("is-ready");
          plate.removeAttribute("src");
        });
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
        /* The drawer takes focus when it opens and the nav behind it goes
           inert, so on Escape there was nowhere for focus to fall but BODY —
           and from BODY the next Tab restarts at the top of the document.
           Dismissing a menu should not cost you your place. The lightbox in
           this same file already restores to its opener; this is that, for
           the control that owns the drawer. After setMenu(false), because the
           burger is inside the region setInert() was just holding. */
        burger?.focus();
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

    /* A swipe is one finger, mostly sideways, on an unzoomed page. The old
       handler read any 55px of horizontal travel on any finger, so the one
       gesture a phone has for looking closer at a painting — pinching out —
       moved the viewer to the next work, and left the reader zoomed in on a
       picture they had not chosen. Panning a zoomed page is not a swipe
       either. */
    let touch = null;
    lb.addEventListener(
      "touchstart",
      (e) => {
        touch =
          e.touches.length === 1
            ? { x: e.touches[0].clientX, y: e.touches[0].clientY }
            : null;
      },
      { passive: true }
    );
    lb.addEventListener(
      "touchend",
      (e) => {
        const start = touch;
        touch = null;
        if (!start || e.touches.length) return;
        if (window.visualViewport && visualViewport.scale > 1.01) return;
        const dx = e.changedTouches[0].clientX - start.x;
        const dy = e.changedTouches[0].clientY - start.y;
        if (Math.abs(dx) > 55 && Math.abs(dx) > Math.abs(dy) * 1.5) {
          show(cursor + (dx < 0 ? 1 : -1));
        }
      },
      { passive: true }
    );

    collectLightbox();
  }

  /* --------------------------------------------------------------- print */
  /* Lazy pictures below the fold were never fetched, so a printed /obrazy
     had twelve sheets of empty frames. Asked to print, every picture loads;
     a browser that snapshots before they arrive gets them on the next print. */
  addEventListener("beforeprint", () => {
    $$('img[loading="lazy"]').forEach((i) => (i.loading = "eager"));
  });

  /* --------------------------------------------------------- partner marks */
  /* Which ground did each logo bring? Read from its corners: transparent,
     light paper or black. The stylesheet picks the filter that drops that
     ground under the screen blend (site.css, .person__logo). */
  $$(".person__logo").forEach((logo) => {
    const classify = () => {
      try {
        const c = document.createElement("canvas");
        const n = (c.width = c.height = 16);
        const g = c.getContext("2d", { willReadFrequently: true });
        g.drawImage(logo, 0, 0, n, n);
        const d = g.getImageData(0, 0, n, n).data;
        let alpha = 0;
        let light = 0;
        [0, n - 1, n * (n - 1), n * n - 1].forEach((p) => {
          alpha += d[p * 4 + 3];
          light += 0.2126 * d[p * 4] + 0.7152 * d[p * 4 + 1] + 0.0722 * d[p * 4 + 2];
        });
        if (alpha / 4 < 128) return;
        logo.classList.add(light / 4 > 128 ? "is-on-light" : "is-on-dark");
      } catch {
        /* An unreadable image keeps the default treatment. */
      }
    };
    if (logo.complete && logo.naturalWidth) classify();
    else logo.addEventListener("load", classify, { once: true });
  });

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
    mapSlot.classList.add("is-loaded");
    // The button is gone, and focus with it, unless it moves to the map.
    frame.focus();
  });
})();
