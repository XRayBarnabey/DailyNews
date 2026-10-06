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

  locations.addEventListener("click", async (event) => {
    const checkButton = event.target.closest("[data-check-weather]");
    if (!checkButton) return;
    const row = checkButton.closest("[data-weather-location]");
    const result = row.querySelector("[data-weather-result]");
    const latitude = row.querySelector("[data-city-latitude]").value;
    const longitude = row.querySelector("[data-city-longitude]").value;
    result.classList.remove("is-error");
    if (!latitude || !longitude) {
      result.classList.add("is-error");
      result.textContent = "Choisissez d’abord une suggestion dans la liste.";
      return;
    }
    const params = new URLSearchParams({
      name: row.querySelector("[data-city-name]").value.trim(),
      latitude,
      longitude,
      timezone: row.querySelector("[data-city-timezone]").value || "auto",
    });
    checkButton.disabled = true;
    result.textContent = "Récupération en cours…";
    try {
      const response = await fetch(`/api/weather/preview?${params}`, { credentials: "same-origin" });
      if (!response.ok) throw new Error();
      const data = await response.json();
      const format = (label, period) =>
        `${label} : ${period.temperature === null ? "—" : `${Math.round(period.temperature)}°`}, ${period.condition}, pluie ${
          period.precipitation_probability === null ? "—" : `${period.precipitation_probability} %`
        }`;
      if (data.morning.temperature === null && data.afternoon.temperature === null) {
        result.classList.add("is-error");
        result.textContent = "Aucune prévision reçue d’Open-Meteo.";
      } else {
        result.textContent = `✓ ${format("Matin", data.morning)} — ${format("Après-midi", data.afternoon)}`;
      }
    } catch {
      result.classList.add("is-error");
      result.textContent = "Impossible de contacter le service météo.";
    } finally {
      checkButton.disabled = false;
    }
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
    const rows = [...locations.querySelectorAll("[data-weather-location]")];
    const entries = [];
    for (const row of rows) {
      const name = row.querySelector("[data-city-name]").value.trim();
      const latitude = row.querySelector("[data-city-latitude]").value;
      const longitude = row.querySelector("[data-city-longitude]").value;
      if (!name || latitude === "" || longitude === "") {
        event.preventDefault();
        const result = row.querySelector("[data-weather-result]");
        result.classList.add("is-error");
        result.textContent = "Choisissez une suggestion dans la liste pour cette ville avant d’enregistrer.";
        row.querySelector("[data-city-name]").focus();
        return;
      }
      entries.push({
        name,
        latitude: Number(latitude),
        longitude: Number(longitude),
        timezone: row.querySelector("[data-city-timezone]").value || "auto",
      });
    }
    serialized.value = JSON.stringify(entries);
  });
});
