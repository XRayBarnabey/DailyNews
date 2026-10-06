document.addEventListener("DOMContentLoaded", () => {
  const form = document.querySelector("[data-settings-form]");
  const locations = document.querySelector("[data-weather-locations]");
  const template = document.querySelector("#weather-location-template");
  const serialized = document.querySelector("#weather-locations-json");
  const addButton = document.querySelector("[data-add-weather-location]");
  const pendingSearches = new WeakMap();

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

  locations.addEventListener("input", (event) => {
    const cityInput = event.target.closest("[data-city-name]");
    if (!cityInput) return;
    const row = cityInput.closest("[data-weather-location]");
    const suggestions = row.querySelector("[data-city-suggestions]");
    row.querySelector("[data-city-latitude]").value = "";
    row.querySelector("[data-city-longitude]").value = "";
    row.querySelector("[data-city-timezone]").value = "auto";
    clearTimeout(pendingSearches.get(cityInput));
    suggestions.replaceChildren();
    const query = cityInput.value.trim();
    if (query.length < 2) return;

    const timer = setTimeout(async () => {
      try {
        const response = await fetch(`/api/weather/cities?q=${encodeURIComponent(query)}`, { credentials: "same-origin" });
        if (!response.ok) return;
        const cities = await response.json();
        if (cityInput.value.trim() !== query) return;
        for (const city of cities) {
          const option = document.createElement("button");
          option.type = "button";
          option.className = "city-suggestion";
          option.setAttribute("role", "option");
          option.textContent = [city.name, city.admin1].filter(Boolean).join(" · ");
          option.addEventListener("click", () => {
            cityInput.value = city.name;
            row.querySelector("[data-city-latitude]").value = city.latitude;
            row.querySelector("[data-city-longitude]").value = city.longitude;
            row.querySelector("[data-city-timezone]").value = city.timezone || "auto";
            suggestions.replaceChildren();
          });
          suggestions.append(option);
        }
      } catch {
        suggestions.replaceChildren();
      }
    }, 250);
    pendingSearches.set(cityInput, timer);
  });

  form.addEventListener("submit", (event) => {
    const entries = [...locations.querySelectorAll("[data-weather-location]")].map((row) => ({
      name: row.querySelector("[data-location-name]").value.trim(),
      latitude: Number(row.querySelector("[data-city-latitude]").value),
      longitude: Number(row.querySelector("[data-city-longitude]").value),
      timezone: row.querySelector("[data-city-timezone]").value || "auto",
    }));
    if (entries.some((location) => !location.name || !Number.isFinite(location.latitude) || !Number.isFinite(location.longitude))) {
      event.preventDefault();
      return;
    }
    serialized.value = JSON.stringify(entries);
  });
});
