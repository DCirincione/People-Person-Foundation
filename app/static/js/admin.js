"use strict";
const csrf = document.querySelector('meta[name="csrf-token"]').content;
async function api(path, options = {}) {
  const headers = {...options.headers, "X-CSRF-Token": csrf};
  const response = await fetch(path, {...options, headers});
  if (response.status === 401 && !document.getElementById("admin-login")) {
    location.href = "/admin/login";
    throw new Error("Please sign in again.");
  }
  if (response.status === 204) return null;
  const body = await response.json();
  if (!response.ok) {
    const detail = typeof body.detail === "string" ? body.detail : "Check all fields and try again.";
    throw new Error(detail);
  }
  return body;
}
function json(method, body) { return {method, headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)}; }
const login = document.getElementById("admin-login");
if (login) login.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = login.querySelector("button");
  button.disabled = true;
  try {
    await api("/admin/login", json("POST", {password: login.elements.password.value, csrf}));
    location.href = "/admin";
  } catch (error) { document.getElementById("login-status").textContent = error.message; }
  finally { button.disabled = false; }
});

const editor = document.getElementById("site-editor");
if (editor) {
  let content, dirty = false, pendingUploads = 0, offset = 0;
  const status = document.getElementById("admin-status");
  const save = document.getElementById("save-content");
  const hint = document.getElementById("save-hint");
  const changed = () => { dirty = true; hint.textContent = "You have unsaved changes."; };
  window.addEventListener("beforeunload", (event) => { if (dirty || pendingUploads) { event.preventDefault(); event.returnValue = ""; } });
  editor.addEventListener("input", changed);
  async function upload(file) {
    if (!file) return null;
    if (file.size > 4 * 1024 * 1024) throw new Error("Choose an image smaller than 4 MB.");
    pendingUploads++;
    save.disabled = true;
    status.textContent = "Uploading photo…";
    try {
      const data = new FormData(); data.append("file", file);
      const result = await api("/admin/api/images", {method: "POST", body: data});
      status.textContent = "Photo uploaded. Save changes to publish it.";
      changed();
      return result.url;
    } finally { pendingUploads--; save.disabled = pendingUploads > 0 || !content; }
  }
  function renderTeam() {
    const container = document.getElementById("team-editor");
    container.replaceChildren();
    content.team.forEach((person, index) => {
      const row = document.getElementById("person-template").content.firstElementChild.cloneNode(true);
      const photo = row.querySelector("img"), placeholder = row.querySelector(".person-photo > span");
      function showPhoto() {
        photo.hidden = !person.image; placeholder.hidden = !!person.image;
        if (person.image) photo.src = person.image;
      }
      showPhoto();
      for (const field of ["name", "role"]) {
        const input = row.querySelector(`[data-field="${field}"]`);
        input.value = person[field];
        input.addEventListener("input", () => { person[field] = input.value; });
      }
      row.querySelector('[data-field="photo"]').addEventListener("change", async (event) => {
        const input = event.target; input.disabled = true;
        try { const url = await upload(input.files[0]); if (url) { person.image = url; showPhoto(); } }
        catch (error) { status.textContent = error.message; }
        finally { input.disabled = false; input.value = ""; }
      });
      row.querySelector('[data-action="clear-photo"]').addEventListener("click", () => { person.image = null; showPhoto(); changed(); });
      row.querySelector('[data-action="remove"]').addEventListener("click", () => {
        if (confirm(`Remove ${person.name || "this person"} from the team? This takes effect when you save.`)) { content.team.splice(index, 1); changed(); renderTeam(); }
      });
      for (const [action, step] of [["up", -1], ["down", 1]]) {
        const button = row.querySelector(`[data-action="${action}"]`);
        button.disabled = index + step < 0 || index + step >= content.team.length;
        button.addEventListener("click", () => { [content.team[index], content.team[index + step]] = [content.team[index + step], content.team[index]]; changed(); renderTeam(); });
      }
      container.append(row);
    });
  }
  document.getElementById("add-person").addEventListener("click", () => {
    if (!content) return;
    if (content.team.length >= 100) { status.textContent = "The team can have up to 100 people."; return; }
    content.team.push({id: crypto.randomUUID(), name: "", role: "", image: null}); changed(); renderTeam();
    document.querySelector('#team-editor .person-editor:last-child input[data-field="name"]').focus();
  });
  document.getElementById("hero-file").addEventListener("change", async (event) => {
    const input = event.target; input.disabled = true;
    try {
      const url = await upload(input.files[0]);
      if (url) { content.hero_image = url; document.getElementById("hero-preview").src = url; }
    } catch (error) { status.textContent = error.message; }
    finally { input.disabled = false; input.value = ""; }
  });
  editor.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!content || pendingUploads || save.disabled) return;
    for (const field of ["hero_alt", "about_title", "about_lead", "about_body"]) content[field] = document.getElementById(field.replaceAll("_", "-")).value;
    const controls = [...editor.elements].map((control) => [control, control.disabled]);
    controls.forEach(([control]) => { control.disabled = true; });
    status.textContent = "Saving…";
    try {
      const saved = await api("/admin/api/content", json("PUT", content));
      content.revision = saved.revision;
      dirty = false; hint.textContent = "All changes saved.";
      status.textContent = "Saved. Your changes are live on the homepage.";
    } catch (error) { status.textContent = error.message; }
    finally { controls.forEach(([control, disabled]) => { control.disabled = disabled; }); }
  });
  api("/admin/api/content").then((data) => {
    content = data;
    document.getElementById("hero-preview").src = content.hero_image;
    for (const field of ["hero_alt", "about_title", "about_lead", "about_body"]) document.getElementById(field.replaceAll("_", "-")).value = content[field];
    renderTeam(); document.getElementById("editor-fields").disabled = false; save.disabled = false; hint.textContent = "Changes publish when you save.";
  }).catch((error) => { status.textContent = error.message; hint.textContent = "Could not load content. Reload to try again."; });

  function element(tag, text, className) {
    const node = document.createElement(tag); if (text) node.textContent = text; if (className) node.className = className; return node;
  }
  let messageRequest = 0, mailFilter = "all";
  async function loadMessages() {
    const sequence = ++messageRequest;
    const list = document.getElementById("message-list");
    list.textContent = "Loading messages…";
    try {
      const filterQuery = mailFilter === "all" ? "" : `&is_read=${mailFilter === "read"}`;
      const messages = await api(`/admin/api/messages?offset=${offset}${filterQuery}`);
      if (sequence !== messageRequest) return;
      if (!messages.length && offset > 0) {
        offset = Math.max(0, offset - 50);
        return loadMessages();
      }
      list.replaceChildren();
      if (!messages.length) list.append(element("p", mailFilter === "all" ? "No messages yet. New contact submissions will appear here." : `No ${mailFilter} messages.`, "admin-panel"));
      messages.forEach((message) => {
        const card = element("details", "", `message-card${message.is_read ? " is-read" : ""}`);
        const header = element("summary", "", "message-summary");
        const timestamp = element("time", new Date(message.created_at).toLocaleString()); timestamp.dateTime = message.created_at;
        const readState = element("span", message.is_read ? "Read" : "Unread", "message-read-state");
        const preview = element("span", message.message.replace(/\s+/g, " "), "message-preview");
        header.append(element("span", message.name, "message-sender"), readState, preview, timestamp);
        const details = element("div", "", "message-details");
        const meta = element("div", "", "message-meta");
        const email = element("a", message.email); email.href = `mailto:${message.email}`; meta.append(email);
        if (message.phone) meta.append(element("span", message.phone));
        const footer = element("div", "", "message-footer");
        const labels = {sent: "Email notification sent", failed: "Email notification failed — message saved here", pending: "Email notification pending"};
        footer.append(element("small", labels[message.delivery] || "Message saved"));
        const toggle = element("button", message.is_read ? "Mark unread" : "Mark read", "secondary-button");
        toggle.addEventListener("click", async () => {
          toggle.disabled = true;
          try {
            await api(`/admin/api/messages/${message.id}`, json("PATCH", {is_read: !message.is_read}));
            message.is_read = !message.is_read; readState.textContent = message.is_read ? "Read" : "Unread"; card.classList.toggle("is-read", !!message.is_read); toggle.textContent = message.is_read ? "Mark unread" : "Mark read";
            if (mailFilter !== "all") await loadMessages();
          } catch (error) { status.textContent = error.message; }
          finally { toggle.disabled = false; }
        });
        footer.append(toggle); details.append(meta, element("p", message.message, "message-body"), footer); card.append(header, details); list.append(card);
      });
      document.getElementById("previous-page").disabled = offset === 0;
      document.getElementById("next-page").disabled = messages.length < 50;
      document.getElementById("message-page").textContent = `Page ${offset / 50 + 1}`;
    } catch (error) { list.textContent = error.message; }
  }
  for (const name of ["editor", "messages", "newsletter"]) document.getElementById(`${name}-tab`).addEventListener("click", () => {
    for (const tab of ["editor", "messages", "newsletter"]) {
      document.getElementById(`${tab}-section`).hidden = tab !== name;
      document.getElementById(`${tab}-tab`).setAttribute("aria-pressed", String(tab === name));
    }
    status.textContent = "";
    if (name === "messages") loadMessages();
    if (name === "newsletter") loadNewsletter();
  });
  document.querySelectorAll("[data-mail-filter]").forEach((button) => {
    button.addEventListener("click", () => {
      mailFilter = button.dataset.mailFilter;
      offset = 0;
      document.querySelectorAll("[data-mail-filter]").forEach((filter) => {
        filter.setAttribute("aria-pressed", String(filter.dataset.mailFilter === mailFilter));
      });
      loadMessages();
    });
  });
  document.getElementById("refresh-messages").addEventListener("click", loadMessages);
  document.getElementById("previous-page").addEventListener("click", () => { offset = Math.max(0, offset - 50); loadMessages(); });
  document.getElementById("next-page").addEventListener("click", () => { offset += 50; loadMessages(); });
  document.getElementById("logout").addEventListener("click", async () => {
    if (dirty && !confirm("Sign out and discard unsaved changes?")) return;
    try { await api("/admin/logout", {method: "POST"}); dirty = false; location.href = "/admin/login"; }
    catch (error) { status.textContent = error.message; }
  });
}

let newsletterBusy = false;
let campaignId = null;
let subscriberCount = 0;
function campaignProgress(job) {
  return `${job.sent} accepted · ${job.pending} remaining · ${job.failed} failed · ${job.sending} unconfirmed · ${job.skipped} unsubscribed`;
}
async function loadNewsletter() {
  const status = document.getElementById("admin-status");
  try {
    const data = await api("/admin/api/newsletter");
    subscriberCount = data.subscribers;
    document.getElementById("subscriber-count").textContent = `${subscriberCount} active subscriber${subscriberCount === 1 ? "" : "s"}`;
    const history = document.getElementById("newsletter-history");
    history.replaceChildren();
    for (const job of data.campaigns) {
      const card = document.createElement("article"); card.className = "admin-panel";
      const title = document.createElement("h3"); title.textContent = job.subject;
      const progress = document.createElement("p"); progress.textContent = `${new Date(job.created_at).toLocaleString()} — ${campaignProgress(job)}`;
      card.append(title, progress);
      if (job.pending) {
        const button = document.createElement("button"); button.className = "secondary-button"; button.textContent = "Continue sending"; button.disabled = newsletterBusy;
        button.addEventListener("click", () => sendNewsletter(job.id)); card.append(button);
      }
      history.append(card);
    }
    if (!data.campaigns.length) history.textContent = "No emails sent yet.";
  } catch (error) { status.textContent = error.message; }
}
async function sendNewsletter(id) {
  if (newsletterBusy) return;
  newsletterBusy = true;
  const status = document.getElementById("admin-status");
  document.querySelector('#newsletter-compose button').disabled = true;
  try {
    let job;
    do {
      job = await api(`/admin/api/newsletter/${id}/send`, {method: "POST"});
      status.textContent = campaignProgress(job);
      if (job.last_failed) { status.textContent += ". Sending paused after a failure. Check email settings before continuing."; break; }
    } while (job.pending > 0);
    if (!job.pending) status.textContent = `Sending finished. ${campaignProgress(job)}`;
  } catch (error) { status.textContent = `${error.message} Refresh to review delivery progress before continuing.`; }
  finally { newsletterBusy = false; document.querySelector('#newsletter-compose button').disabled = false; await loadNewsletter(); }
}
const composer = document.getElementById("newsletter-compose");
if (composer) {
  document.getElementById("refresh-newsletter").addEventListener("click", loadNewsletter);
  composer.addEventListener("input", () => { campaignId = null; });
  window.addEventListener("beforeunload", (event) => { if (newsletterBusy) { event.preventDefault(); event.returnValue = ""; } });
  composer.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (newsletterBusy) return;
    if (!confirm(`Send “${composer.elements.subject.value}” to all active subscribers (${subscriberCount} at last refresh)?`)) return;
    const button = composer.querySelector("button"); button.disabled = true;
    campaignId ||= crypto.randomUUID();
    try {
      const job = await api("/admin/api/newsletter", json("POST", {id: campaignId, subject: composer.elements.subject.value, body: composer.elements.body.value}));
      composer.reset(); campaignId = null;
      await sendNewsletter(job.id);
    } catch (error) { document.getElementById("admin-status").textContent = error.message; }
    finally { button.disabled = false; }
  });
}
