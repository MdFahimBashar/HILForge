(() => {
  "use strict";

  const form = document.getElementById("run-form");
  if (!form) return;

  const scopeInputs = [...form.querySelectorAll('input[name="scope"]')];
  const targetFieldset = document.getElementById("device-targets");
  const checkboxes = [...form.querySelectorAll(".device-checkbox:not([disabled])")];
  const selectedCount = document.getElementById("selected-count");
  const selectAvailable = document.getElementById("select-available");
  const submit = form.querySelector('[data-testid="run-submit"]');
  const submitLabel = submit.querySelector(".button-label");
  const message = document.getElementById("run-message");

  const selectedScope = () => form.querySelector('input[name="scope"]:checked').value;
  const selectedDevices = () => checkboxes.filter((checkbox) => checkbox.checked);

  const updateState = () => {
    const isSelected = selectedScope() === "selected";
    const count = selectedDevices().length;
    targetFieldset.disabled = !isSelected;
    selectedCount.textContent = `${count} selected`;
    submitLabel.textContent = isSelected
      ? count === 1
        ? "Run on selected device"
        : `Run on ${count} selected devices`
      : `Run on ${checkboxes.length} available devices`;
    submit.disabled = isSelected ? count === 0 : checkboxes.length === 0;
    message.textContent = "";
    message.classList.remove("is-error");
  };

  scopeInputs.forEach((input) => input.addEventListener("change", updateState));
  checkboxes.forEach((checkbox) => checkbox.addEventListener("change", updateState));
  selectAvailable.addEventListener("click", () => {
    const shouldSelect = checkboxes.some((checkbox) => !checkbox.checked);
    checkboxes.forEach((checkbox) => {
      checkbox.checked = shouldSelect;
    });
    selectAvailable.textContent = shouldSelect ? "Clear selection" : "Select available";
    updateState();
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const targeted = selectedScope() === "selected";
    const deviceIds = selectedDevices().map((checkbox) => checkbox.value);
    if (targeted && deviceIds.length === 0) {
      message.textContent = "Select at least one available device.";
      message.classList.add("is-error");
      return;
    }

    const payload = { test_suite_id: document.getElementById("suite").value };
    if (targeted) payload.device_ids = deviceIds;
    const originalLabel = submitLabel.textContent;
    submit.disabled = true;
    submit.classList.add("is-loading");
    submitLabel.textContent = "Creating run";
    message.textContent = "Reserving devices and queueing jobs…";

    try {
      const response = await fetch("/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "The run could not be created.");
      message.textContent = "Run created. Opening live results…";
      window.location.assign(`/runs/${data.id}/view`);
    } catch (error) {
      submit.disabled = false;
      submit.classList.remove("is-loading");
      submitLabel.textContent = originalLabel;
      message.textContent = error.message;
      message.classList.add("is-error");
    }
  });

  updateState();
})();
