const pointData = {
    origin: {lat:48.8566,lng:2.3522,fields:["origin-lat","origin-lng"],marker:null},
    destination: {lat:48.8584,lng:2.2945,fields:["destination-lat","destination-lng"],marker:null},
  };
  let activePoint="origin", map, geometry, vehicleMarker, routeBaseLine, traveledLine, remainingLine, routePath=[], segmentLengths=[], totalMeters=0;
  let routeDuration=0, simulatedBeforePause=0, runStartedAt=0, running=false, intervalId=null, speedFactor=60;
  const $=id=>document.getElementById(id);
  const message=$("message");
  const apiTokenInput=$("api-token");
  apiTokenInput.value=sessionStorage.getItem("greenlineApiToken")||"";
  apiTokenInput.addEventListener("input",()=>sessionStorage.setItem("greenlineApiToken",apiTokenInput.value.trim()));

  function setMessage(text,error=false) { message.textContent=text; message.classList.toggle("error",error); }
  function pointPayload(name) { return {latitude:pointData[name].lat,longitude:pointData[name].lng}; }
  function syncPoint(name) {
    const point=pointData[name];
    point.fields.forEach((id,index)=>$(id).value=(index===0?point.lat:point.lng).toFixed(6));
    if(point.marker) point.marker.setPosition({lat:point.lat,lng:point.lng});
  }
  function readFields() {
    for(const [name,point] of Object.entries(pointData)) {
      const lat=Number($(point.fields[0]).value), lng=Number($(point.fields[1]).value);
      if(!Number.isFinite(lat)||!Number.isFinite(lng)||Math.abs(lat)>90||Math.abs(lng)>180) throw new Error("Vérifiez les coordonnées GPS saisies.");
      point.lat=lat; point.lng=lng;
      if(point.marker) point.marker.setPosition({lat,lng});
    }
  }
  for(const [name,point] of Object.entries(pointData)) point.fields.forEach((id,index)=>$(id).addEventListener("change",event=>{
    const value=Number(event.target.value); if(!Number.isFinite(value)) return;
    if(index===0) point.lat=value; else point.lng=value;
    if(point.marker) point.marker.setPosition({lat:point.lat,lng:point.lng});
  }));
  function setActivePoint(name) {
    activePoint=name;
    document.querySelectorAll(".select-btn").forEach(button=>button.classList.toggle("active",button.dataset.point===name));
  }
  document.querySelectorAll(".select-btn").forEach(button=>button.addEventListener("click",()=>setActivePoint(button.dataset.point)));

  function drawInitialRoute(path) {
    if(routeBaseLine) routeBaseLine.setMap(null);
    if(traveledLine) traveledLine.setMap(null);
    if(remainingLine) remainingLine.setMap(null);
    routeBaseLine=new google.maps.Polyline({map,path,strokeColor:"#b9c8c0",strokeOpacity:.9,strokeWeight:9,zIndex:1});
    traveledLine=new google.maps.Polyline({map,path:[],strokeColor:"#147d55",strokeOpacity:1,strokeWeight:5,zIndex:3});
    remainingLine=new google.maps.Polyline({map,path,strokeColor:"#3478f6",strokeOpacity:1,strokeWeight:5,zIndex:2});
    routePath=path;
    segmentLengths=[]; totalMeters=0;
    for(let i=1;i<path.length;i++) { const length=geometry.spherical.computeDistanceBetween(path[i-1],path[i]); segmentLengths.push(length); totalMeters+=length; }
    const bounds=new google.maps.LatLngBounds(); path.forEach(point=>bounds.extend(point)); map.fitBounds(bounds,60);
  }
  function positionAt(distance) {
    if(routePath.length===1||totalMeters===0) return {position:routePath[routePath.length-1],passed:routePath.slice(0,1)};
    let traversed=0;
    for(let i=0;i<segmentLengths.length;i++) {
      const length=segmentLengths[i];
      if(distance<=traversed+length||i===segmentLengths.length-1) {
        const ratio=length===0?1:Math.min(1,Math.max(0,(distance-traversed)/length));
        const position=geometry.spherical.interpolate(routePath[i],routePath[i+1],ratio);
        return {position,passed:[...routePath.slice(0,i+1),position],remaining:[position,...routePath.slice(i+1)]};
      }
      traversed+=length;
    }
    return {position:routePath[routePath.length-1],passed:routePath,remaining:[routePath[routePath.length-1]]};
  }
  function elapsedSimulationSeconds() { return simulatedBeforePause+(running?(Date.now()-runStartedAt)/1000*speedFactor:0); }
  function formatDuration(seconds) {
    const mins=Math.max(0,Math.ceil(seconds/60));
    return mins<60?`${mins} min`:`${Math.floor(mins/60)} h ${mins%60} min`;
  }
  function renderProgress() {
    if(!routePath.length) return;
    const elapsed=Math.min(routeDuration,elapsedSimulationSeconds()), ratio=routeDuration===0?1:elapsed/routeDuration;
    const distance=Math.min(totalMeters,totalMeters*ratio), progress=positionAt(distance);
    vehicleMarker.setPosition(progress.position); traveledLine.setPath(progress.passed); remainingLine.setPath(progress.remaining);
    const remainingSeconds=Math.max(0,routeDuration-elapsed), remainingMeters=Math.max(0,totalMeters-distance);
    $("progress-value").textContent=`${Math.round(ratio*100)} %`;
    $("progress-bar").style.width=`${ratio*100}%`;
    $("remaining-distance").textContent=`${(remainingMeters/1000).toFixed(1).replace(".",",")} km restants`;
    $("remaining-time").textContent=`${formatDuration(remainingSeconds/speedFactor)} simulées`;
    $("arrival-time").textContent=remainingSeconds===0?"Véhicule arrivé":`Arrivée simulée vers ${new Intl.DateTimeFormat("fr-FR",{hour:"2-digit",minute:"2-digit"}).format(new Date(Date.now()+remainingSeconds/speedFactor*1000))}`;
    if(ratio>=1) { stopTimer(); simulatedBeforePause=routeDuration; running=false; $("pause").disabled=true; $("pause").textContent="Mettre en pause"; setMessage("Simulation terminée : le véhicule est arrivé."); }
  }
  function stopTimer() { if(intervalId) clearInterval(intervalId); intervalId=null; }
  function startTimer() { stopTimer(); intervalId=setInterval(renderProgress,Number($("interval").value)*1000); }
  async function startSimulation() {
    if(routePath.length&&!running&&simulatedBeforePause<routeDuration) {
      running=true; runStartedAt=Date.now(); speedFactor=Number($("speed").value); startTimer(); $("pause").disabled=false; $("pause").textContent="Mettre en pause"; setMessage("Simulation en cours…"); return;
    }
    let data;
    try {
      readFields(); setMessage("Calcul de l’itinéraire…"); $("start").disabled=true;
      const response=await fetch("/api/v1/eta",{method:"POST",headers:{"Content-Type":"application/json","X-API-Token":apiTokenInput.value.trim()},body:JSON.stringify({origin:pointPayload("origin"),destination:pointPayload("destination")})});
      const envelope=await response.json(); if(!response.ok) throw new Error(envelope.message||"Le calcul de l’itinéraire a échoué."); data=envelope.data;
      if(!data.encoded_polyline) throw new Error("L’API n’a pas renvoyé la géométrie du trajet.");
      const path=geometry.encoding.decodePath(data.encoded_polyline); if(path.length<2) throw new Error("L’itinéraire renvoyé est incomplet.");
      drawInitialRoute(path); routeDuration=Math.max(1,Number(data.duration_seconds));
      simulatedBeforePause=0; speedFactor=Number($("speed").value); running=true; runStartedAt=Date.now(); vehicleMarker.setMap(map);
      vehicleMarker.setPosition(path[0]); $("stats").classList.add("show"); $("pause").disabled=false; $("pause").textContent="Mettre en pause";
      setMessage(`Simulation démarrée · durée réelle du trajet : ${formatDuration(routeDuration)}.`); renderProgress(); startTimer();
    } catch(error) { setMessage(error.message,true); }
    finally { $("start").disabled=false; }
  }
  $("start").addEventListener("click",startSimulation);
  $("pause").addEventListener("click",()=>{
    if(running) { simulatedBeforePause=elapsedSimulationSeconds(); running=false; stopTimer(); renderProgress(); $("pause").textContent="Reprendre"; setMessage("Simulation en pause."); }
    else startSimulation();
  });
  $("reset").addEventListener("click",()=>{
    stopTimer(); running=false; routePath=[]; simulatedBeforePause=0; routeDuration=0;
    if(routeBaseLine) routeBaseLine.setMap(null); if(traveledLine) traveledLine.setMap(null); if(remainingLine) remainingLine.setMap(null); if(vehicleMarker) vehicleMarker.setMap(null);
    routeBaseLine=null; traveledLine=null; remainingLine=null; $("stats").classList.remove("show"); $("pause").disabled=true; $("pause").textContent="Mettre en pause";
    setMessage("Simulation réinitialisée. Choisissez les points puis démarrez.");
  });
  $("interval").addEventListener("change",()=>{ if(running) startTimer(); });
  $("speed").addEventListener("change",()=>{
    if(running) { simulatedBeforePause=elapsedSimulationSeconds(); runStartedAt=Date.now(); speedFactor=Number($("speed").value); renderProgress(); }
    else speedFactor=Number($("speed").value);
  });

  async function initMap() {
    try {
      const {Map}=await google.maps.importLibrary("maps"), {Marker}=await google.maps.importLibrary("marker");
      geometry=await google.maps.importLibrary("geometry");
      map=new Map($("map"),{center:{lat:48.8566,lng:2.32},zoom:12,mapTypeControl:false,streetViewControl:false,fullscreenControl:true});
      pointData.origin.marker=new Marker({map,position:{lat:pointData.origin.lat,lng:pointData.origin.lng},title:"Départ",icon:{path:google.maps.SymbolPath.CIRCLE,scale:9,fillColor:"#16865d",fillOpacity:1,strokeColor:"#fff",strokeWeight:2}});
      pointData.destination.marker=new Marker({map,position:{lat:pointData.destination.lat,lng:pointData.destination.lng},title:"Arrivée",icon:{path:google.maps.SymbolPath.CIRCLE,scale:9,fillColor:"#e06b50",fillOpacity:1,strokeColor:"#fff",strokeWeight:2}});
      vehicleMarker=new Marker({map,position:{lat:pointData.origin.lat,lng:pointData.origin.lng},title:"Véhicule",zIndex:10,icon:{path:google.maps.SymbolPath.CIRCLE,scale:8,fillColor:"#3478f6",fillOpacity:1,strokeColor:"#fff",strokeWeight:3}});
      vehicleMarker.setMap(null);
      const bounds=new google.maps.LatLngBounds(); bounds.extend(pointData.origin.marker.getPosition()); bounds.extend(pointData.destination.marker.getPosition()); map.fitBounds(bounds,70);
      map.addListener("click",event=>{pointData[activePoint].lat=event.latLng.lat();pointData[activePoint].lng=event.latLng.lng();syncPoint(activePoint);});
    } catch(error) { $("map-error").classList.add("show"); }
  }
  window.initMap=initMap;
  async function loadMap() {
    try {
      const response=await fetch("/api/v1/config"),envelope=await response.json(),config=envelope.data;
      if(!config.google_maps_api_key) { $("map-error").classList.add("show"); return; }
      const script=document.createElement("script");
      script.src=`https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(config.google_maps_api_key)}&v=weekly&loading=async&callback=initMap`;
      script.async=true; script.defer=true; script.onerror=()=>$("map-error").classList.add("show"); document.head.appendChild(script);
    } catch(error) { $("map-error").classList.add("show"); }
  }
  loadMap();
