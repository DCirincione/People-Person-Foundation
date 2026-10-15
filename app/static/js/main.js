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
