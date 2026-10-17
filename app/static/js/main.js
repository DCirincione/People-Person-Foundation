"use strict";

document.querySelectorAll("[data-dialog]").forEach((button) => {
  button.addEventListener("click", () => {
    const dialog = document.getElementById(`dialog-${button.dataset.dialog}`);
    if (dialog) dialog.showModal();
  });
});

document.querySelectorAll("dialog").forEach((dialog) => {
  dialog.addEventListener("click", (event) => {
    const bounds = dialog.getBoundingClientRect();
    if (event.target === dialog && (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom)) {
      dialog.close();
    }
  });
});

const contactForm = document.getElementById("contact-form");
if (contactForm) {
  contactForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = contactForm.querySelector('[type="submit"]');
    if (button.disabled) return;
    const status = document.getElementById("contact-status");
    const values = Object.fromEntries(new FormData(contactForm));
    const originalLabel = button.innerHTML;
    button.disabled = true;
    button.textContent = "Sending…";
    status.textContent = "";
    contactForm.setAttribute("aria-busy", "true");
    try {
      const response = await fetch("/api/contact", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(values),
      });
      const result = await response.json();
      if (!response.ok) {
        throw new Error(typeof result.detail === "string" ? result.detail : "Please check your details and try again.");
      }
      status.textContent = result.message;
      contactForm.reset();
    } catch (error) {
      status.textContent = error instanceof TypeError ? "We couldn’t confirm your message was sent. Please try again or email us directly." : error.message;
    } finally {
      button.disabled = false;
      button.innerHTML = originalLabel;
      contactForm.removeAttribute("aria-busy");
    }
  });
}

// Five consecutive header-logo clicks open the protected admin login.
const headerLogo = document.querySelector(".site-header .brand");
if (headerLogo) {
  let count = 0, timer;
  headerLogo.addEventListener("click", (event) => {
    if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button !== 0) return;
    event.preventDefault();
    clearTimeout(timer);
    count++;
    if (count === 5) { count = 0; location.href = "/admin"; return; }
    timer = setTimeout(() => { count = 0; location.href = headerLogo.href; }, 750);
  });
  document.addEventListener("click", (event) => {
    if (!headerLogo.contains(event.target)) { clearTimeout(timer); count = 0; }
  });
}

const signupForm = document.getElementById("newsletter-signup");
if (signupForm) signupForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = signupForm.querySelector('[type="submit"]');
  if (button.disabled) return;
  button.disabled = true;
  const status = document.getElementById("signup-status");
  status.textContent = "Signing up…";
  try {
    const response = await fetch("/api/newsletter/subscribe", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({email: signupForm.elements.email.value})});
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Please enter a valid email address.");
    status.textContent = data.message;
    signupForm.reset();
  } catch (error) { status.textContent = error instanceof TypeError ? "Could not save your signup. Please try again." : error.message; }
  finally { button.disabled = false; }
});

// An informational notice, separate from newsletter opt-in and cookie consent.
(() => {
  const notice = document.getElementById("privacy-notice");
  if (!notice) return;
  const key = "ppf-privacy-notice-v1";
  try { if (localStorage.getItem(key) === "dismissed") return; }
  catch { /* The notice still works when browser storage is unavailable. */ }
  notice.hidden = false;
  document.getElementById("privacy-dismiss").addEventListener("click", () => {
    try { localStorage.setItem(key, "dismissed"); }
    catch { /* Dismiss for this page even if the preference cannot be saved. */ }
    notice.hidden = true;
  });
})();
