"use strict";
(() => {
  const launcher = document.getElementById("accessibility-button");
  const panel = document.getElementById("accessibility-panel");
  if (!launcher || !panel || typeof panel.showModal !== "function") return;
  const key = "ppf-accessibility-v1";
  const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const defaults = () => ({largeText: false, highContrast: false, reducedMotion: motion.matches, underlineLinks: false});
  let preferences = defaults();
  try {
    const stored = JSON.parse(localStorage.getItem(key));
    for (const name of Object.keys(preferences)) {
      if (stored && typeof stored[name] === "boolean") preferences[name] = stored[name];
    }
  } catch { /* Browser storage can be disabled; controls still work for this page. */ }
  function apply() {
    // Always respect the operating system's reduced-motion preference.
    preferences.reducedMotion = preferences.reducedMotion || motion.matches;
    for (const [name, enabled] of Object.entries(preferences)) {
      document.documentElement.classList.toggle(`a11y-${name}`, enabled);
      const button = panel.querySelector(`[data-accessibility="${name}"]`);
      button.setAttribute("aria-pressed", String(enabled));
      button.querySelector(".accessibility-state").textContent = enabled ? "On" : "Off";
    }
  }
  function persist() {
    try { localStorage.setItem(key, JSON.stringify(preferences)); }
    catch { /* Preferences still apply without persistent storage. */ }
  }
  launcher.hidden = false;
  apply();
  launcher.addEventListener("click", () => { if (!panel.open) panel.showModal(); });
  document.getElementById("accessibility-close").addEventListener("click", () => panel.close());
  // Native dialog provides modal focus containment and Escape dismissal.
  panel.addEventListener("close", () => launcher.focus({preventScroll: true}));
  panel.querySelectorAll("[data-accessibility]").forEach((button) => {
    button.addEventListener("click", () => {
      const name = button.dataset.accessibility;
      if (name === "reducedMotion" && motion.matches) {
        document.getElementById("accessibility-status").textContent = "Reduced motion is enabled by your device settings.";
        return;
      }
      preferences[name] = !preferences[name];
      apply(); persist();
    });
  });
  document.getElementById("accessibility-reset").addEventListener("click", () => {
    preferences = defaults(); apply();
    try { localStorage.removeItem(key); } catch { /* Storage is optional. */ }
    document.getElementById("accessibility-status").textContent = "Preferences reset. Your device’s motion preference is respected.";
  });
  motion.addEventListener("change", () => { apply(); });
})();
