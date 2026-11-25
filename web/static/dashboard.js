let cachedLeads = [];

const badge = (text, cls) => `<span class="badge badge-${cls}">${text}</span>`;

function openDrawer(lead) {
  document.getElementById("drawerTitle").textContent = `${lead.lead_name} — ${lead.room_name}`;
  document.getElementById("drawerMeta").innerHTML = `
    <div class="kv"><span class="k">Email</span><span class="v">${lead.lead_email || "—"}</span></div>
    <div class="kv"><span class="k">Current Role</span><span class="v">${lead.current_role || "—"}</span></div>
    <div class="kv"><span class="k">Target Course</span><span class="v">${lead.target_course || "—"}</span></div>
    <div class="kv"><span class="k">Timeline / Budget</span><span class="v">${lead.timeline || "—"} / ${lead.budget_comfort || "—"}</span></div>
    <div class="kv"><span class="k">Booking</span><span class="v">${lead.booking_status} ${lead.booking_time ? `(${lead.booking_time})` : ""}</span></div>
    <div class="kv"><span class="k">Booking UID</span><span class="v">${lead.booking_uid || "—"}</span></div>
    <div class="kv"><span class="k">Executive Summary</span><span class="v">${lead.summary || "Pending call end"}</span></div>
    <div class="kv"><span class="k">Next Best Action</span><span class="v" style="color:var(--teal)">${lead.next_action || "—"}</span></div>
  `;

  const box = document.getElementById("drawerTranscript");
  box.innerHTML = "";
  if (!lead.transcript || lead.transcript.length === 0) {
    box.innerHTML = `<div class="msg event">No transcript entries recorded.</div>`;
  } else {
    lead.transcript.forEach((t) => {
      const div = document.createElement("div");
      div.className = `msg ${t.role === "user" ? "user" : "assistant"}`;
      div.innerHTML = `<div class="msg-meta"><strong>${t.agent || t.role}</strong><span>${t.ts || ""}</span></div><div>${t.text}</div>`;
      box.appendChild(div);
    });
  }
  document.getElementById("detailDrawer").classList.add("open");
}

async function loadDashboard() {
  try {
    const [statsRes, leadsRes] = await Promise.all([
      fetch("/api/crm/stats"),
      fetch("/api/crm/leads"),
    ]);
    const stats = await statsRes.json();
    const { leads } = await leadsRes.json();
    cachedLeads = leads || [];

    document.getElementById("kpiCalls").textContent = stats.total_calls;
    document.getElementById("kpiHot").textContent = stats.hot_leads;
    document.getElementById("kpiBooked").textContent = stats.booked_meetings;
    document.getElementById("kpiAvg").textContent = stats.avg_lead_score;
    document.getElementById("kpiFailovers").textContent = stats.failover_recoveries;

    const tbody = document.getElementById("leadsBody");
    if (cachedLeads.length === 0) {
      tbody.innerHTML = `<tr><td colspan="7" style="color:var(--muted);text-align:center;padding:24px;">No calls logged yet. Run a voice call from the Voice Console.</td></tr>`;
      return;
    }

    tbody.innerHTML = cachedLeads
      .map((l, idx) => {
        const tierCls = l.lead_tier === "Hot" ? "green" : l.lead_tier === "Warm" ? "amber" : "slate";
        const sentCls = l.sentiment === "Positive" ? "green" : l.sentiment === "Hesitant" ? "amber" : l.sentiment === "Negative" ? "red" : "slate";
        const bookCls = l.booking_status === "Confirmed" ? "green" : "slate";
        const provCls = l.failover_events > 0 ? "amber" : "indigo";
        return `
          <tr data-idx="${idx}">
            <td><strong>${l.lead_name}</strong><div style="font-size:11px;color:var(--muted)">${l.lead_email || l.room_name}</div></td>
            <td>${l.target_course || "—"}</td>
            <td>${badge(`${l.lead_score} · ${l.lead_tier}`, tierCls)}</td>
            <td>${badge(l.sentiment, sentCls)}</td>
            <td>${badge(l.booking_status, bookCls)}<div style="font-size:11px;color:var(--muted);margin-top:3px;">${l.booking_time || ""}</div></td>
            <td>${badge(l.active_provider, provCls)}<div style="font-size:11px;color:var(--muted);margin-top:3px;">${l.failover_events} failovers</div></td>
            <td style="max-width:280px;color:var(--muted);">${l.summary || "In progress..."}</td>
          </tr>
        `;
      })
      .join("");

    tbody.querySelectorAll("tr[data-idx]").forEach((row) => {
      row.addEventListener("click", () => openDrawer(cachedLeads[Number(row.dataset.idx)]));
    });
  } catch (err) {
    console.error("Dashboard load error:", err);
  }
}

document.getElementById("refreshBtn").addEventListener("click", loadDashboard);
document.getElementById("closeDrawer").addEventListener("click", () => {
  document.getElementById("detailDrawer").classList.remove("open");
});

loadDashboard();
setInterval(loadDashboard, 5000);
