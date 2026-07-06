// Simple navbar UTC clock
document.addEventListener("DOMContentLoaded", () => {
  const clockEl = document.getElementById("navbar-clock");
  if (!clockEl) return;

  const updateClock = () => {
    const now = new Date();
    clockEl.textContent = now.toISOString().slice(0, 19).replace("T", " UTC ");
  };

  updateClock();
  setInterval(updateClock, 30_000);
});

