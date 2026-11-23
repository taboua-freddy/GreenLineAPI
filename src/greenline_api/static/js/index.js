const points = {
    origin: { lat: 48.8566, lng: 2.3522, marker: null, fields: ["origin-lat", "origin-lng"] },
    destination: { lat: 48.8584, lng: 2.2945, marker: null, fields: ["destination-lat", "destination-lng"] },
  };
  let activePoint = "origin", map, routeLine;
  const message = document.getElementById("message");
  const resultBox = document.getElementById("result");
  const apiTokenInput = document.getElementById("api-token");
  apiTokenInput.value = sessionStorage.getItem("greenlineApiToken") || "";
  apiTokenInput.addEventListener("input", () => sessionStorage.setItem("greenlineApiToken", apiTokenInput.value.trim()));

  function updatePoint(name, lat, lng) {
    points[name].lat = lat; points[name].lng = lng;
    document.getElementById(points[name].fields[0]).value = lat.toFixed(6);
    document.getElementById(points[name].fields[1]).value = lng.toFixed(6);
    if (points[name].marker) points[name].marker.setPosition({lat, lng});
  }
  function setActivePoint(name) {
    activePoint = name;
    document.querySelectorAll(".select-btn").forEach(button => button.classList.toggle("active", button.dataset.point === name));
  }
  document.querySelectorAll(".select-btn").forEach(button => button.addEventListener("click", () => setActivePoint(button.dataset.point)));
  for (const [name, point] of Object.entries(points)) {
    point.fields.forEach((id, index) => document.getElementById(id).addEventListener("change", event => {
      const value = Number(event.target.value);
      if (!Number.isFinite(value)) return;
      if (index === 0) point.lat = value; else point.lng = value;
      if (point.marker) point.marker.setPosition({lat: point.lat, lng: point.lng});
    }));
  }

  async function initMap() {
    try {
      const { Map } = await google.maps.importLibrary("maps");
      const { Marker } = await google.maps.importLibrary("marker");
      const { encoding } = await google.maps.importLibrary("geometry");
      map = new Map(document.getElementById("map"), { center: {lat:48.8566,lng:2.32}, zoom:12, mapTypeControl:false, streetViewControl:false, fullscreenControl:true });
      points.origin.marker = new Marker({map, position:{lat:points.origin.lat,lng:points.origin.lng}, title:"Départ", icon:{path:google.maps.SymbolPath.CIRCLE,scale:9,fillColor:"#16865d",fillOpacity:1,strokeColor:"#ffffff",strokeWeight:2}});
      points.destination.marker = new Marker({map, position:{lat:points.destination.lat,lng:points.destination.lng}, title:"Arrivée", icon:{path:google.maps.SymbolPath.CIRCLE,scale:9,fillColor:"#e06b50",fillOpacity:1,strokeColor:"#ffffff",strokeWeight:2}});
      const bounds = new google.maps.LatLngBounds();
      bounds.extend(points.origin.marker.getPosition()); bounds.extend(points.destination.marker.getPosition()); map.fitBounds(bounds, 70);
      map.addListener("click", event => updatePoint(activePoint, event.latLng.lat(), event.latLng.lng()));
      window.drawRoute = encoded => {
        if (routeLine) routeLine.setMap(null);
        routeLine = new google.maps.Polyline({map, path:encoding.decodePath(encoded), strokeColor:"#147d55", strokeOpacity:.9, strokeWeight:5});
        const routeBounds = new google.maps.LatLngBounds(); routeLine.getPath().forEach(point => routeBounds.extend(point)); map.fitBounds(routeBounds, 60);
      };
    } catch (error) { showMapError(); }
  }
  window.initMap = initMap;
  function showMapError() { document.getElementById("map-error").classList.add("show"); }

  async function loadMap() {
    try {
      const response = await fetch("/api/v1/config");
      const envelope = await response.json();
      const config = envelope.data;
      if (!config.google_maps_api_key) { showMapError(); return; }
      const script = document.createElement("script");
      script.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(config.google_maps_api_key)}&v=weekly&loading=async&callback=initMap`;
      script.async = true; script.defer = true; script.onerror = showMapError; document.head.appendChild(script);
    } catch (error) { showMapError(); }
  }

  document.getElementById("calculate").addEventListener("click", async () => {
    const button = document.getElementById("calculate");
    message.classList.remove("error"); message.textContent = "Calcul de l’itinéraire…"; resultBox.classList.remove("show"); button.disabled = true;
    try {
      const response = await fetch("/api/v1/eta", {method:"POST", headers:{"Content-Type":"application/json","X-API-Token":apiTokenInput.value.trim()}, body:JSON.stringify({origin:{latitude:points.origin.lat,longitude:points.origin.lng},destination:{latitude:points.destination.lat,longitude:points.destination.lng}})});
      const envelope = await response.json();
      if (!response.ok) throw new Error(envelope.message || "Le calcul de l’ETA a échoué.");
      const data = envelope.data;
      document.getElementById("eta-time").textContent = new Intl.DateTimeFormat("fr-FR", {hour:"2-digit",minute:"2-digit",timeZone:"Europe/Paris"}).format(new Date(data.eta_at));
      const minutes = Math.round(data.duration_seconds / 60);
      document.getElementById("duration").textContent = minutes < 60 ? `${minutes} min` : `${Math.floor(minutes/60)} h ${minutes%60} min`;
      document.getElementById("distance").textContent = `${(data.distance_meters/1000).toFixed(1).replace(".",",")} km`;
      resultBox.classList.add("show"); message.textContent = "Itinéraire calculé.";
      if (window.drawRoute && data.encoded_polyline) window.drawRoute(data.encoded_polyline);
    } catch (error) { message.textContent = error.message; message.classList.add("error"); }
    finally { button.disabled = false; }
  });
  loadMap();
