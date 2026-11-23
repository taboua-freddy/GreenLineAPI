const parcInput = document.getElementById("parc-id");
const tokenInput = document.getElementById("api-token");
const lookupButton = document.getElementById("lookup");
const statusMessage = document.getElementById("status");
const resultPanel = document.getElementById("result");

tokenInput.value = sessionStorage.getItem("greenlineApiToken") || "";
tokenInput.addEventListener("input", () => {
  sessionStorage.setItem("greenlineApiToken", tokenInput.value.trim());
});

function setStatus(message, isError = false) {
  statusMessage.textContent = message;
  statusMessage.classList.toggle("error", isError);
}

lookupButton.addEventListener("click", async () => {
  const parcId = parcInput.value.trim().toUpperCase();
  if (!/^(PF|ST|CO|ME)-\d+$/.test(parcId)) {
    resultPanel.hidden = true;
    setStatus("Format invalide. Utilisez par exemple PF-1233, ST-1233, CO-1233 ou ME-1233.", true);
    return;
  }

  lookupButton.disabled = true;
  resultPanel.hidden = true;
  setStatus(`Récupération du GPS et recherche de l’adresse pour ${parcId}…`);
  document.getElementById("json-response").textContent = "Requête en cours…";
  try {
    const response = await fetch("/api/v1/telematics/location", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-API-Token": tokenInput.value.trim(),
      },
      body: JSON.stringify({parc_id: parcId}),
    });
    const envelope = await response.json();
    document.getElementById("json-response").textContent = JSON.stringify(envelope, null, 2);
    if (!response.ok) {
      const detail = envelope.errors?.map(error => error.message).join(" · ");
      throw new Error(detail || envelope.message || `Erreur HTTP ${response.status}`);
    }

    const data = envelope.data;
    document.getElementById("result-parc").textContent = data.parc_id;
    document.getElementById("address").textContent = data.address;
    document.getElementById("latitude").textContent = Number(data.latitude).toFixed(6);
    document.getElementById("longitude").textContent = Number(data.longitude).toFixed(6);
    document.getElementById("badge").textContent = data.equipped ? "Télématique active" : "Non équipé";
    document.getElementById("position-date").textContent = data.position_date
      ? `Dernier relevé GPS : ${new Date(data.position_date).toLocaleString("fr-FR", {dateStyle:"medium", timeStyle:"short"})}`
      : "Date du relevé non fournie par Hiboo.";
    document.getElementById("map-link").href = `https://www.google.com/maps?q=${encodeURIComponent(data.latitude)},${encodeURIComponent(data.longitude)}`;
    resultPanel.hidden = false;
    setStatus(envelope.message || "Adresse et coordonnées récupérées.");
  } catch (error) {
    setStatus(error.message || "La requête a échoué.", true);
  } finally {
    lookupButton.disabled = false;
  }
});
