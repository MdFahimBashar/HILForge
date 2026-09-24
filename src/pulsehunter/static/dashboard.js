(() => {
  "use strict";

  const form = document.getElementById("run-form");
  if (!form) return;

  const suite = document.getElementById("suite");
  const targetFieldset = document.getElementById("device-targets");
  const checkboxes = [...form.querySelectorAll(".device-checkbox")];
  const selectedCount = document.getElementById("selected-count");
  const selectAvailable = document.getElementById("select-available");
  const submit = form.querySelector('[data-testid="run-submit"]');
  const submitLabel = submit.querySelector(".button-label");
  const message = document.getElementById("run-message");
  let creatingRun = false;

  const selectedScope = () => form.querySelector('input[name="scope"]:checked').value;
  const suiteSlug = () => suite.selectedOptions[0]?.dataset.suiteSlug;
  const compatible = (checkbox) => checkbox.dataset.supportedSuites.split(",").includes(suiteSlug());
  const available = () => checkboxes.filter((checkbox) => !checkbox.disabled);
  const selected = () => available().filter((checkbox) => checkbox.checked);

  const updateState = () => {
    const targeted = selectedScope() === "selected";
    checkboxes.forEach((checkbox) => {
      const canRun = checkbox.dataset.deviceStatus === "online" && compatible(checkbox);
      checkbox.disabled = !canRun;
      if (!canRun) checkbox.checked = false;
      checkbox.closest(".target-device").classList.toggle("is-unavailable", !canRun);
    });
    const count = targeted ? selected().length : available().length;
    targetFieldset.disabled = !targeted;
    selectedCount.textContent = `${selected().length} selected`;
    submitLabel.textContent = count === 1
      ? "Run on 1 compatible device"
      : `Run on ${count} compatible devices`;
    submit.disabled = creatingRun || count === 0;
    selectAvailable.textContent = selected().length === available().length && available().length
      ? "Clear selection" : "Select available";
    if (!creatingRun && !message.classList.contains("is-error")) {
      message.textContent = available().length === 0
        ? "No online devices support this suite."
        : targeted && count === 0 ? "Choose at least one compatible device." : "";
      message.classList.remove("is-error");
    }
  };

  const onSelectionChange = () => {
    message.classList.remove("is-error");
    updateState();
  };
  form.querySelectorAll('input[name="scope"]').forEach((input) => input.addEventListener("change", onSelectionChange));
  suite.addEventListener("change", onSelectionChange);
  checkboxes.forEach((checkbox) => checkbox.addEventListener("change", onSelectionChange));
  selectAvailable.addEventListener("click", () => {
    const shouldSelect = available().some((checkbox) => !checkbox.checked);
    available().forEach((checkbox) => { checkbox.checked = shouldSelect; });
    onSelectionChange();
  });

  const refreshDevices = async () => {
    if (creatingRun || document.hidden) return;
    try {
      const response = await fetch("/devices", { cache: "no-store" });
      if (!response.ok) return;
      const devices = await response.json();
      const knownIds = new Set(checkboxes.map((checkbox) => checkbox.value));
      if (devices.some((device) => !knownIds.has(device.id))) {
        window.location.reload();
        return;
      }
      const counts = { online: 0, busy: 0, offline: 0 };
      const rows = new Map([...document.querySelectorAll("[data-device-id]")]
        .map((row) => [row.dataset.deviceId, row]));
      devices.forEach((device) => {
        counts[device.status] += 1;
        const checkbox = checkboxes.find((item) => item.value === device.id);
        if (checkbox) {
          checkbox.dataset.deviceStatus = device.status;
          checkbox.dataset.supportedSuites = (device.capabilities.supported_suites ||
            (device.device_type === "simulator" ? ["smoke"] : [])).join(",");
          const state = checkbox.closest(".target-device").querySelector(".target-state");
          state.className = `target-state state-${device.status}`;
          state.lastChild.textContent = device.status.charAt(0).toUpperCase() + device.status.slice(1);
        }
        const row = rows.get(device.id);
        if (row) {
          const badge = row.querySelector(".status-badge");
          badge.className = `status-badge status-${device.status}`;
          badge.lastChild.textContent = device.status.charAt(0).toUpperCase() + device.status.slice(1);
          const heartbeat = row.querySelector('[data-label="Last heartbeat"]');
          if (device.last_heartbeat_at) {
            let time = heartbeat.querySelector("time");
            if (!time) {
              time = document.createElement("time");
              time.dataset.relativeTime = "";
              heartbeat.replaceChildren(time);
            }
            time.dateTime = device.last_heartbeat_at;
            time.title = new Date(device.last_heartbeat_at).toLocaleString();
            time.textContent = new Date(device.last_heartbeat_at).toLocaleString();
          }
        }
      });
      document.getElementById("fleet-count").textContent = devices.length;
      document.getElementById("online-count").textContent = counts.online;
      document.getElementById("ready-count").textContent = counts.online;
      document.getElementById("busy-count").textContent = counts.busy;
      document.getElementById("offline-count").textContent = counts.offline;
      document.getElementById("available-count").textContent = counts.online;
      updateState();
    } catch (_) {
      // Keep the last server-rendered state until the API can be reached again.
    }
  };

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const deviceIds = (selectedScope() === "selected" ? selected() : available())
      .map((checkbox) => checkbox.value);
    if (!deviceIds.length) {
      message.textContent = "Select at least one online device supporting this suite.";
      message.classList.add("is-error");
      return;
    }

    creatingRun = true;
    submit.disabled = true;
    submit.classList.add("is-loading");
    submitLabel.textContent = "Creating run";
    message.textContent = "Reserving devices and queueing jobs…";
    message.classList.remove("is-error");

    try {
      const response = await fetch("/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ test_suite_id: suite.value, device_ids: deviceIds }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "The run could not be created.");
      message.textContent = "Run created. Opening live results…";
      window.location.assign(`/runs/${data.id}/view`);
    } catch (error) {
      creatingRun = false;
      submit.classList.remove("is-loading");
      updateState();
      message.textContent = error.message;
      message.classList.add("is-error");
    }
  });

  updateState();
  window.setInterval(refreshDevices, 5000);
})();
