document.addEventListener("DOMContentLoaded", () => {
  const form = document.querySelector("[data-settings-form]");
  const locations = document.querySelector("[data-weather-locations]");
  const template = document.querySelector("#weather-location-template");
  const serialized = document.querySelector("#weather-locations-json");
  const addButton = document.querySelector("[data-add-weather-location]");

  if (!form || !locations || !template || !serialized || !addButton) return;

  addButton.addEventListener("click", () => {
    if (locations.children.length >= 10) return;
    locations.append(template.content.cloneNode(true));
    locations.lastElementChild.querySelector("input").focus();
  });

  locations.addEventListener("click", (event) => {
    const removeButton = event.target.closest("[data-remove-weather-location]");
    if (removeButton && locations.children.length > 1) removeButton.closest("[data-weather-location]").remove();
  });

  form.addEventListener("submit", (event) => {
    const entries = [...locations.querySelectorAll("[data-weather-location]")].map((row) => ({
      name: row.querySelector("[data-location-name]").value.trim(),
      latitude: Number(row.querySelector("[data-location-latitude]").value),
      longitude: Number(row.querySelector("[data-location-longitude]").value),
    }));
    if (entries.some((location) => !location.name || !Number.isFinite(location.latitude) || !Number.isFinite(location.longitude))) {
      event.preventDefault();
      return;
    }
    serialized.value = JSON.stringify(entries);
  });
});
