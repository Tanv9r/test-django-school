/* Appointment booking helpers: filter doctors by department and show free slots.
   The server re-validates availability and conflicts on submit. */
(function () {
  "use strict";
  var form = document.querySelector("[data-appointment-form]");
  if (!form) return;

  var department = form.querySelector("#id_department");
  var doctor = form.querySelector("#id_doctor");
  var date = form.querySelector("#id_date");
  var time = form.querySelector("#id_time");
  var panel = document.querySelector("[data-slot-panel]");
  var slotsUrl = form.dataset.slotsUrl;
  var excludeId = form.dataset.appointmentId || "";

  function filterDoctors() {
    var dept = department.value;
    Array.prototype.forEach.call(doctor.options, function (opt) {
      if (!opt.value) return;
      var match = !dept || opt.dataset.department === dept;
      opt.hidden = !match;
      opt.disabled = !match;
    });
    var selected = doctor.selectedOptions[0];
    if (selected && selected.disabled) doctor.value = "";
  }

  function syncDepartment() {
    var selected = doctor.selectedOptions[0];
    if (selected && selected.dataset.department && !department.value) {
      department.value = selected.dataset.department;
      filterDoctors();
    }
  }

  function render(html) { panel.innerHTML = html; }

  function loadSlots() {
    if (!doctor.value || !date.value) {
      render('<p class="text-muted small mb-0"><i class="bi bi-info-circle"></i> Choose a doctor and date to see free time slots.</p>');
      return;
    }
    render('<div class="d-flex align-items-center gap-2 text-muted small"><span class="spinner-border spinner-border-sm"></span> Checking availability…</div>');
    var url = slotsUrl + "?doctor=" + encodeURIComponent(doctor.value) + "&date=" + encodeURIComponent(date.value) + "&exclude=" + encodeURIComponent(excludeId);
    fetch(url, { headers: { "X-Requested-With": "XMLHttpRequest" }, credentials: "same-origin" })
      .then(function (r) { return r.json().then(function (body) { return { ok: r.ok, body: body }; }); })
      .then(function (res) {
        if (!res.ok) { render('<p class="text-danger small mb-0">' + escapeHtml(res.body.error || "Could not load slots.") + "</p>"); return; }
        var data = res.body;
        var hours = data.working_hours.length ? data.working_hours.map(escapeHtml).join(", ") : "Not working on this day";
        var html = '<div class="small text-muted mb-2"><i class="bi bi-clock"></i> Working hours: ' + hours + " · " + data.slot_minutes + "-minute slots</div>";
        if (!data.slots.length) {
          html += '<div class="alert alert-warning py-2 mb-0 small"><i class="bi bi-calendar-x"></i> No free slots on this date.</div>';
        } else {
          html += '<div class="d-flex flex-wrap gap-2">' + data.slots.map(function (s) {
            var active = time.value && time.value.slice(0, 5) === s ? " btn-primary" : " btn-light";
            return '<button type="button" class="btn btn-sm' + active + '" data-slot="' + s + '">' + s + "</button>";
          }).join("") + "</div>";
        }
        render(html);
      })
      .catch(function () { render('<p class="text-danger small mb-0">Could not load slots. You can still type a time manually.</p>'); });
  }

  function escapeHtml(text) {
    var div = document.createElement("div");
    div.textContent = String(text);
    return div.innerHTML;
  }

  panel.addEventListener("click", function (event) {
    var btn = event.target.closest("[data-slot]");
    if (!btn) return;
    time.value = btn.dataset.slot;
    panel.querySelectorAll("[data-slot]").forEach(function (b) { b.classList.remove("btn-primary"); b.classList.add("btn-light"); });
    btn.classList.add("btn-primary");
    btn.classList.remove("btn-light");
  });

  department.addEventListener("change", function () { filterDoctors(); loadSlots(); });
  doctor.addEventListener("change", function () { syncDepartment(); loadSlots(); });
  date.addEventListener("change", loadSlots);
  filterDoctors();
  loadSlots();
})();
