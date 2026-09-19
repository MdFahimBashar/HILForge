(() => {
  "use strict";

  const relativeLabel = (date) => {
    const seconds = Math.round((date.getTime() - Date.now()) / 1000);
    const absolute = Math.abs(seconds);
    if (absolute < 8) return "just now";
    const ranges = [
      [60, "second"],
      [60, "minute"],
      [24, "hour"],
      [7, "day"],
      [4.345, "week"],
      [12, "month"],
      [Number.POSITIVE_INFINITY, "year"],
    ];
    let value = seconds;
    for (const [limit, unit] of ranges) {
      if (Math.abs(value) < limit) {
        return new Intl.RelativeTimeFormat(undefined, { numeric: "auto" }).format(
          Math.round(value),
          unit,
        );
      }
      value /= limit;
    }
    return date.toLocaleString();
  };

  const updateRelativeTimes = () => {
    document.querySelectorAll("time[data-relative-time]").forEach((element) => {
      const date = new Date(element.dateTime);
      if (!Number.isNaN(date.getTime())) element.textContent = relativeLabel(date);
    });
  };

  document.querySelectorAll("tr[data-href]").forEach((row) => {
    const navigate = () => window.location.assign(row.dataset.href);
    row.addEventListener("click", (event) => {
      if (!event.target.closest("a, button, input, select, details, summary")) navigate();
    });
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter") navigate();
    });
  });

  const autoRefresh = document.querySelector("[data-auto-refresh]");
  if (autoRefresh) {
    const interval = Number(autoRefresh.dataset.autoRefresh);
    if (Number.isFinite(interval) && interval > 0) window.setTimeout(() => window.location.reload(), interval);
  }

  updateRelativeTimes();
  window.setInterval(updateRelativeTimes, 30000);
  document.documentElement.classList.add("ui-ready");
})();
