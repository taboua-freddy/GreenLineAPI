const idsInput = document.getElementById("parc-ids");
  const apiTokenInput = document.getElementById("api-token");
  apiTokenInput.value = sessionStorage.getItem("greenlineApiToken") || "";
  apiTokenInput.addEventListener("input", () => sessionStorage.setItem("greenlineApiToken", apiTokenInput.value.trim()));
  const buttons = [document.getElementById("check-button"), document.getElementById("positions-button"), document.getElementById("location-button")];

  function parseParcIds() {
    const ids = [...new Set(idsInput.value.split(/[\s,;]+/).map(value => value.trim().toUpperCase()).filter(Boolean))];
    if (!ids.length) throw new Error("Saisissez au moins un identifiant de parc.");
    const invalid = ids.filter(id => !/^(PF|ST|CO|ME)-\d+$/.test(id));
    if (invalid.length) throw new Error(`Format invalide : ${invalid.join(", ")}.`);
    return ids;
  }

  function requestBody(ids) {
    return ids.length === 1 ? {parc_id: ids[0]} : {parc_ids: ids};
  }

  function setStatus(kind, text, isError = false) {
    const status = document.getElementById(`${kind}-status`);
    status.textContent = text;
    status.classList.toggle("error", isError);
  }

  function showEmpty(kind, text) {
    const box = document.getElementById(`${kind}-results`);
    box.replaceChildren();
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = text;
    box.append(empty);
  }

  function showCheckResults(vehicles) {
    const box = document.getElementById("check-results");
    box.replaceChildren();
    for (const vehicle of vehicles || []) {
      const row = document.createElement("article");
      row.className = "vehicle";
      const info = document.createElement("div");
      const id = document.createElement("div");
      id.className = "vehicle-id";
      id.textContent = vehicle.parc_id;
      const meta = document.createElement("div");
      meta.className = "vehicle-meta";
      meta.textContent = vehicle.equipment_id == null ? "Aucun équipement Hiboo associé" : `ID Hiboo : ${vehicle.equipment_id}`;
      info.append(id, meta);
      const badge = document.createElement("span");
      badge.className = `badge ${vehicle.equipped ? "yes" : "no"}`;
      badge.textContent = vehicle.equipped ? "Équipé" : "Non équipé";
      row.append(info, badge);
      box.append(row);
    }
    if (!vehicles?.length) showEmpty("check", "Aucun véhicule retourné.");
  }

  function showPositionResults(vehicles) {
    const box = document.getElementById("positions-results");
    box.replaceChildren();
    for (const vehicle of vehicles || []) {
      const row = document.createElement("article");
      row.className = "vehicle";
      const info = document.createElement("div");
      const id = document.createElement("div");
      id.className = "vehicle-id";
      id.textContent = vehicle.parc_id;
      info.append(id);
      const position = vehicle.position;
      if (position) {
        const coords = document.createElement("div");
        coords.className = "position";
        coords.textContent = `${Number(position.latitude).toFixed(6)}, ${Number(position.longitude).toFixed(6)}`;
        const link = document.createElement("a");
        link.href = `https://www.google.com/maps?q=${encodeURIComponent(position.latitude)},${encodeURIComponent(position.longitude)}`;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.textContent = "Ouvrir la carte";
        coords.append(document.createTextNode(" · "), link);
        if (position.date) {
          const date = document.createElement("div");
          date.className = "vehicle-meta";
          const parsedDate = new Date(position.date);
          date.textContent = Number.isNaN(parsedDate.getTime()) ? position.date : `Dernier relevé : ${parsedDate.toLocaleString("fr-FR", {dateStyle:"medium", timeStyle:"short"})}`;
          info.append(date);
        }
        info.append(coords);
      } else {
        const meta = document.createElement("div");
        meta.className = "vehicle-meta";
        meta.textContent = vehicle.equipped ? "Aucune position disponible" : "Véhicule non équipé en télématique";
        info.append(meta);
      }
      const badge = document.createElement("span");
      badge.className = `badge ${position ? "yes" : vehicle.equipped ? "missing" : "no"}`;
      badge.textContent = position ? "Position reçue" : vehicle.equipped ? "Sans position" : "Non équipé";
      row.append(info, badge);
      box.append(row);
    }
    if (!vehicles?.length) showEmpty("positions", "Aucun véhicule retourné.");
  }

  async function callEndpoint(kind, path, renderer) {
    let ids;
    try { ids = parseParcIds(); }
    catch (error) { setStatus(kind, error.message, true); showEmpty(kind, "Corrigez la saisie puis réessayez."); return; }
    buttons.forEach(item => item.disabled = true);
    setStatus(kind, `Appel de ${path} pour ${ids.length} véhicule${ids.length > 1 ? "s" : ""}…`);
    document.getElementById(`${kind}-json`).textContent = "Requête en cours…";
    try {
      const response = await fetch(path, {
        method: "POST",
        headers: {"Content-Type":"application/json", "X-API-Token":apiTokenInput.value.trim()},
        body: JSON.stringify(requestBody(ids)),
      });
      const envelope = await response.json();
      document.getElementById(`${kind}-json`).textContent = JSON.stringify(envelope, null, 2);
      if (!response.ok) {
        const detail = envelope.errors?.map(error => error.field ? `${error.field} : ${error.message}` : error.message).join(" · ");
        throw new Error(detail || envelope.message || `Erreur HTTP ${response.status}`);
      }
      renderer(envelope.data?.vehicles);
      setStatus(kind, `${envelope.message || "Terminé."} · ${envelope.data?.vehicles?.length || 0} résultat(s).`);
    } catch (error) {
      setStatus(kind, error.message || "La requête a échoué.", true);
      showEmpty(kind, "Impossible d’afficher les résultats.");
    } finally {
      buttons.forEach(item => item.disabled = false);
    }
  }

  document.getElementById("check-button").addEventListener("click", () =>
    callEndpoint("check", "/api/v1/telematics/check", showCheckResults));
  document.getElementById("positions-button").addEventListener("click", () =>
    callEndpoint("positions", "/api/v1/telematics/positions", showPositionResults));
  document.getElementById("location-button").addEventListener("click", async () => {
    let ids;
    try {
      ids = parseParcIds();
      if (ids.length !== 1) throw new Error("Cette recherche accepte un seul parc à la fois.");
    } catch (error) {
      setStatus("location", error.message, true);
      showEmpty("location", "Corrigez la saisie puis réessayez.");
      return;
    }
    buttons.forEach(item => item.disabled = true);
    setStatus("location", `Recherche de l’adresse de ${ids[0]}…`);
    document.getElementById("location-json").textContent = "Requête en cours…";
    try {
      const response = await fetch("/api/v1/telematics/location", {
        method: "POST",
        headers: {"Content-Type":"application/json", "X-API-Token":apiTokenInput.value.trim()},
        body: JSON.stringify({parc_id: ids[0]}),
      });
      const envelope = await response.json();
      document.getElementById("location-json").textContent = JSON.stringify(envelope, null, 2);
      if (!response.ok) {
        const detail = envelope.errors?.map(error => error.message).join(" · ");
        throw new Error(detail || envelope.message || `Erreur HTTP ${response.status}`);
      }
      const data = envelope.data;
      const box = document.getElementById("location-results");
      box.replaceChildren();
      const row = document.createElement("article"); row.className = "vehicle";
      const info = document.createElement("div");
      const id = document.createElement("div"); id.className = "vehicle-id"; id.textContent = data.parc_id;
      const address = document.createElement("div"); address.className = "vehicle-meta"; address.textContent = data.address;
      const coordinates = document.createElement("div"); coordinates.className = "position";
      coordinates.textContent = `${Number(data.latitude).toFixed(6)}, ${Number(data.longitude).toFixed(6)}`;
      const mapLink = document.createElement("a");
      mapLink.href = `https://www.google.com/maps?q=${encodeURIComponent(data.latitude)},${encodeURIComponent(data.longitude)}`;
      mapLink.target = "_blank"; mapLink.rel = "noopener noreferrer"; mapLink.textContent = "Ouvrir la carte";
      coordinates.append(document.createTextNode(" · "), mapLink);
      info.append(id, address, coordinates);
      if (data.position_date) {
        const date = document.createElement("div"); date.className = "vehicle-meta";
        date.textContent = `Dernier relevé : ${new Date(data.position_date).toLocaleString("fr-FR", {dateStyle:"medium", timeStyle:"short"})}`;
        info.append(date);
      }
      const badge = document.createElement("span"); badge.className = "badge yes"; badge.textContent = "Adresse trouvée";
      row.append(info, badge); box.append(row);
      setStatus("location", envelope.message || "Adresse et coordonnées récupérées.");
    } catch (error) {
      setStatus("location", error.message || "La requête a échoué.", true);
      showEmpty("location", "Impossible d’afficher l’adresse et les coordonnées.");
    } finally {
      buttons.forEach(item => item.disabled = false);
    }
  });
  document.getElementById("clear-button").addEventListener("click", () => {
    for (const kind of ["check", "positions", "location"]) {
      setStatus(kind, "Saisissez un ou plusieurs identifiants.");
      showEmpty(kind, "Les résultats apparaîtront ici.");
      document.getElementById(`${kind}-json`).textContent = "Aucune réponse reçue.";
    }
  });
