/**
 * Title: plySync.js — Current-ply and perspective synchronization
 * Description:
 *   Manages shared analysis state (currentPly, perspective) across all
 *   move-analysis elements — board, PGN table, Stockfish chart, Lc0 chart.
 *   Syncs both values into the URL query string so links embed the current
 *   position and orientation. Each element subscribes via WoodLeagueAnalysis.subscribe()
 *   and receives the full state object on every change.
 *
 * Changelog:
 *   2026-05-04 (#16): Created as part of game analysis page rewrite
 */

(function (global) {
  "use strict";

  const state = {
    ply: 0,
    perspective: "white",
    totalPlies: 0,
  };

  /** @type {Array<function({ply: number, perspective: string, totalPlies: number}): void>} */
  const subscribers = [];

  function _notify() {
    const snapshot = { ply: state.ply, perspective: state.perspective, totalPlies: state.totalPlies };
    subscribers.forEach((fn) => {
      try { fn(snapshot); } catch (e) { console.error("[plySync] subscriber error:", e); }
    });
    _syncUrl();
  }

  function _syncUrl() {
    try {
      const params = new URLSearchParams(window.location.search);
      params.set("ply", state.ply);
      params.set("orientation", state.perspective);
      history.replaceState(null, "", "?" + params.toString());
    } catch (_) {
      // replaceState may fail in some iframes; ignore
    }
  }

  /**
   * Set the current ply and notify all subscribers.
   * @param {number} ply - Zero-based ply index (0 = starting position)
   */
  function setPly(ply) {
    const clamped = Math.max(0, state.totalPlies > 0 ? Math.min(ply, state.totalPlies) : ply);
    if (clamped === state.ply) return;
    state.ply = clamped;
    _notify();
  }

  /**
   * Set the board perspective and notify all subscribers.
   * Board element handles HTMX reload; chart elements flip client-side.
   * @param {string} p - "white" or "black"
   */
  function setPerspective(p) {
    if (p !== "white" && p !== "black") return;
    if (p === state.perspective) return;
    state.perspective = p;
    _notify();
  }

  /**
   * Register the total number of plies so setPly can clamp correctly.
   * Called by the board element after it loads its frame data.
   * @param {number} n
   */
  function setTotalPlies(n) {
    state.totalPlies = n;
  }

  /**
   * Register a subscriber callback that fires on every ply or perspective change.
   * @param {function} fn - Receives { ply, perspective, totalPlies }
   * @returns {function} Unsubscribe function
   */
  function subscribe(fn) {
    subscribers.push(fn);
    return function unsubscribe() {
      const idx = subscribers.indexOf(fn);
      if (idx !== -1) subscribers.splice(idx, 1);
    };
  }

  /** @returns {{ ply: number, perspective: string, totalPlies: number }} */
  function getState() {
    return { ply: state.ply, perspective: state.perspective, totalPlies: state.totalPlies };
  }

  /**
   * Initialise state from URL query params. Call once on page load.
   * @param {{ defaultPly?: number, defaultPerspective?: string }} opts
   */
  function initFromUrl(opts) {
    const params = new URLSearchParams(window.location.search);
    const urlPly = parseInt(params.get("ply") || "", 10);
    const urlOrientation = params.get("orientation");

    state.ply = isNaN(urlPly) ? (opts && opts.defaultPly != null ? opts.defaultPly : 0) : urlPly;
    state.perspective =
      urlOrientation === "black" ? "black" :
      urlOrientation === "white" ? "white" :
      (opts && opts.defaultPerspective ? opts.defaultPerspective : "white");
    // No notify here — elements initialize themselves from getState() on load
  }

  global.WoodLeagueAnalysis = {
    setPly,
    setPerspective,
    setTotalPlies,
    subscribe,
    getState,
    initFromUrl,
  };
})(window);
