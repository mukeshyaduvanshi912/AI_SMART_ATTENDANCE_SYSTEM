// Auto-dismiss flash messages after a few seconds
document.addEventListener("DOMContentLoaded", () => {
  const flashes = document.querySelectorAll(".flash");
  flashes.forEach((el) => {
    setTimeout(() => {
      el.style.transition = "opacity 0.4s ease";
      el.style.opacity = "0";
      setTimeout(() => el.remove(), 400);
    }, 5000);
  });

  // Confirm before triggering webcam-based actions (they block the page process)
  const camForms = document.querySelectorAll("[data-confirm-camera]");
  camForms.forEach((form) => {
    form.addEventListener("submit", (e) => {
      const ok = confirm(
        "This will open the server's webcam window. Focus that window, " +
        "follow the on-screen instructions, and press Q when done. Continue?"
      );
      if (!ok) e.preventDefault();
    });
  });
});
