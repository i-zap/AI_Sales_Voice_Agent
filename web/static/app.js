const { Room, RoomEvent, Track } = window.LivekitClient;

let room = null;
let micMuted = false;
let openaiKilled = false;
let turnCounter = 0;

const el = (id) => document.getElementById(id);

function appendMessage(kind, label, text, extraClass = "") {
  const box = el("transcriptBox");
  const div = document.createElement("div");
  div.className = `msg ${kind} ${extraClass}`.trim();
  if (kind === "event") {
    div.textContent = text;
  } else {
    const meta = document.createElement("div");
    meta.className = "msg-meta";
    meta.innerHTML = `<strong>${label}</strong><span>${new Date().toLocaleTimeString()}</span>`;
    const body = document.createElement("div");
    body.textContent = text;
    div.appendChild(meta);
    div.appendChild(body);
  }
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
}

function setActiveAgent(agentName) {
  ["Orchestrator", "Qualifier", "RAG Advisor", "Booking & CRM"].forEach((name) => {
    const node = el(`node-${name}`);
    if (node) node.classList.toggle("active", name === agentName);
  });
}

function renderBadge(text, style) {
  return `<span class="badge badge-${style}">${text}</span>`;
}

function updateTelemetryUI(data) {
  if (data.active_agent) setActiveAgent(data.active_agent);

  if (data.lead_name && data.lead_name !== "Unknown Prospect") el("leadName").textContent = data.lead_name;
  if (data.lead_email) el("leadEmail").textContent = data.lead_email;
  if (data.target_course) el("targetCourse").textContent = data.target_course;

  const tierStyle = data.lead_tier === "Hot" ? "green" : data.lead_tier === "Warm" ? "amber" : "slate";
  el("leadScore").innerHTML = renderBadge(`${data.lead_score || 0}/100 · ${data.lead_tier || "Unqualified"}`, tierStyle);

  const sentStyle =
    data.sentiment === "Positive" ? "green" :
    data.sentiment === "Hesitant" ? "amber" :
    data.sentiment === "Negative" ? "red" : "slate";
  el("sentimentVal").innerHTML = renderBadge(data.sentiment || "Neutral", sentStyle);

  const bookStyle = data.booking_status === "Confirmed" ? "green" : "slate";
  el("bookingStatus").innerHTML = renderBadge(data.booking_status || "Not Booked", bookStyle);
  if (data.booking_time) el("bookingTime").textContent = data.booking_time;

  // Circuit Breaker & Provider Stack
  el("activeLLM").textContent = data.active_llm || "OpenAI gpt-4.1-mini";
  el("activeSTT").textContent = data.active_stt || "OpenAI gpt-4o-mini-transcribe";
  el("activeTTS").textContent = data.active_tts || "OpenAI gpt-4o-mini-tts";
  el("failoverCount").textContent = String(data.failover_events || 0);

  openaiKilled = Boolean(data.openai_killed);
  const isFailover = openaiKilled || (data.active_llm || "").includes("Groq");
  el("circuitBadge").textContent = data.circuit_status || (isFailover ? "OPEN" : "CLOSED");
  el("circuitBadge").className = `badge ${isFailover ? "badge-red" : "badge-green"}`;
  el("voiceOrb").classList.toggle("failover", isFailover);
  updateChaosButton();

  if (Array.isArray(data.rag_hits) && data.rag_hits.length > 0) {
    el("ragChips").innerHTML = data.rag_hits
      .map((title) => `<span class="badge badge-indigo">${title}</span>`)
      .join("");
  }

  if (data.type === "transcript" && data.last_turn) {
    turnCounter += 1;
    el("turnCount").textContent = `${turnCounter} turns`;
    const t = data.last_turn;
    appendMessage(t.role === "user" ? "user" : "assistant", t.agent || t.role, t.text);
  } else if (data.note) {
    const isFault = ["chaos_engaged", "failover"].includes(data.type);
    appendMessage("event", "", data.note, isFault ? "failover" : "");
  }
}

function updateChaosButton() {
  const btn = el("chaosBtn");
  if (openaiKilled) {
    btn.className = "btn-restore";
    btn.textContent = "Restore OpenAI Primary (Close Circuit)";
  } else {
    btn.className = "btn-chaos";
    btn.textContent = "Simulate OpenAI Outage (Switch to Groq)";
  }
}

async function startCall() {
  const startBtn = el("startBtn");
  startBtn.disabled = true;
  el("statusText").textContent = "Minting LiveKit JWT token & connecting...";

  try {
    const name = el("prospectName").value.trim() || "Prospect";
    const resp = await fetch("/api/token", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ participant_name: name }),
    });
    if (!resp.ok) throw new Error(await resp.text());
    const { token, url, room_name } = await resp.json();

    room = new Room({ adaptiveStream: true, dynacast: true });

    room.on(RoomEvent.TrackSubscribed, (track) => {
      if (track.kind === Track.Kind.Audio) {
        const audioEl = track.attach();
        audioEl.autoplay = true;
        el("audioContainer").appendChild(audioEl);
      }
    });

    room.on(RoomEvent.TrackUnsubscribed, (track) => {
      track.detach().forEach((node) => node.remove());
    });

    room.on(RoomEvent.DataReceived, (payload, _participant, _kind, topic) => {
      if (topic !== "fortivex_telemetry") return;
      try {
        const parsed = JSON.parse(new TextDecoder().decode(payload));
        updateTelemetryUI(parsed);
      } catch (_err) {}
    });

    room.on(RoomEvent.Disconnected, () => {
      resetUI("Call ended. Check CRM Dashboard for post-call summary.");
    });

    await room.connect(url, token);
    await room.localParticipant.setMicrophoneEnabled(true);

    el("roomBadge").textContent = room_name;
    el("roomBadge").className = "badge badge-green";
    el("voiceOrb").textContent = "LIVE";
    el("voiceOrb").className = "voice-orb live";
    el("statusText").textContent = "Connected — speak naturally with Aria";
    el("muteBtn").disabled = false;
    el("endBtn").disabled = false;
    el("chaosBtn").disabled = false;
    appendMessage("event", "", `Joined LiveKit room ${room_name} — awaiting agent greeting...`);
  } catch (err) {
    console.error(err);
    resetUI(`Connection failed: ${err.message}`);
  }
}

function resetUI(msg) {
  el("audioContainer").innerHTML = "";
  el("startBtn").disabled = false;
  el("muteBtn").disabled = true;
  el("endBtn").disabled = true;
  el("chaosBtn").disabled = true;
  el("muteBtn").textContent = "Mute";
  micMuted = false;
  openaiKilled = false;
  updateChaosButton();
  el("roomBadge").textContent = "IDLE";
  el("roomBadge").className = "badge badge-slate";
  el("voiceOrb").textContent = "READY";
  el("voiceOrb").className = "voice-orb";
  el("statusText").textContent = msg;
  room = null;
}

async function toggleMute() {
  if (!room) return;
  micMuted = !micMuted;
  await room.localParticipant.setMicrophoneEnabled(!micMuted);
  el("muteBtn").textContent = micMuted ? "Unmute" : "Mute";
  el("statusText").textContent = micMuted ? "Microphone muted" : "Connected — listening";
}

async function toggleChaos() {
  if (!room) return;
  const action = openaiKilled ? "restore_openai" : "kill_openai";
  const data = new TextEncoder().encode(JSON.stringify({ action }));
  await room.localParticipant.publishData(data, { reliable: true, topic: "fortivex_control" });
}

async function endCall() {
  if (room) await room.disconnect();
}

el("startBtn").addEventListener("click", startCall);
el("muteBtn").addEventListener("click", toggleMute);
el("endBtn").addEventListener("click", endCall);
el("chaosBtn").addEventListener("click", toggleChaos);
