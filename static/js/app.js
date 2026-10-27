/* HMS shared UI behaviour. Business rules live on the server; this file only improves UX. */
(function () {
  "use strict";

  // ---- Sidebar (mobile off-canvas) ----
  document.addEventListener("click", function (event) {
    if (event.target.closest("[data-sidebar-toggle]")) {
      document.body.classList.toggle("sidebar-open");
    } else if (event.target.closest("[data-sidebar-close]")) {
      document.body.classList.remove("sidebar-open");
    }
  });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") document.body.classList.remove("sidebar-open");
  });

  // ---- Confirmation modal for destructive / important actions ----
  var confirmModalEl = document.getElementById("confirmModal");
  var pendingForm = null;
  if (confirmModalEl && window.bootstrap) {
    var confirmModal = new bootstrap.Modal(confirmModalEl);
    document.addEventListener("submit", function (event) {
      var form = event.target;
      if (!form.matches("form[data-confirm]") || form.dataset.confirmed === "1") return;
      event.preventDefault();
      pendingForm = form;
      confirmModalEl.querySelector("[data-confirm-message]").textContent = form.dataset.confirm;
      var button = confirmModalEl.querySelector("[data-confirm-accept]");
      button.className = "btn " + (form.dataset.confirmClass || "btn-danger");
      button.textContent = form.dataset.confirmLabel || "Confirm";
      confirmModal.show();
    }, true);
    confirmModalEl.querySelector("[data-confirm-accept]").addEventListener("click", function () {
      if (!pendingForm) return;
      pendingForm.dataset.confirmed = "1";
      confirmModal.hide();
      if (pendingForm.requestSubmit) pendingForm.requestSubmit(); else pendingForm.submit();
    });
  }

  // ---- Loading state on submit (prevents double submission) ----
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (event.defaultPrevented || !form.matches("form[data-loading]")) return;
    form.querySelectorAll("button[type=submit]").forEach(function (btn) {
      btn.disabled = true;
      btn.dataset.originalHtml = btn.innerHTML;
      btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1" role="status" aria-hidden="true"></span> Saving…';
    });
  });
  // Restore buttons when navigating back (bfcache).
  window.addEventListener("pageshow", function () {
    document.querySelectorAll("button[data-original-html]").forEach(function (btn) {
      btn.disabled = false;
      btn.innerHTML = btn.dataset.originalHtml;
    });
  });

  // ---- Auto-dismiss success / info alerts ----
  document.querySelectorAll(".alert-dismissible.alert-success, .alert-dismissible.alert-info").forEach(function (el) {
    setTimeout(function () {
      if (window.bootstrap && document.body.contains(el)) bootstrap.Alert.getOrCreateInstance(el).close();
    }, 6000);
  });

  // ---- Tooltips ----
  if (window.bootstrap) {
    document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(function (el) { new bootstrap.Tooltip(el); });
  }

  // ---- Dynamic Django formsets ----
  // Markup: <div data-formset="prefix"> rows... <template data-formset-template>…__prefix__…</template>
  //          <button data-formset-add="prefix">
  document.addEventListener("click", function (event) {
    var addBtn = event.target.closest("[data-formset-add]");
    if (addBtn) {
      var prefix = addBtn.dataset.formsetAdd;
      var container = document.querySelector('[data-formset="' + prefix + '"]');
      var template = container.querySelector("template[data-formset-template]");
      var total = document.getElementById("id_" + prefix + "-TOTAL_FORMS");
      var max = document.getElementById("id_" + prefix + "-MAX_NUM_FORMS");
      var index = parseInt(total.value, 10);
      if (max && index >= parseInt(max.value, 10)) return;
      var html = template.innerHTML.replace(/__prefix__/g, index);
      var wrapper = document.createElement("div");
      wrapper.innerHTML = html.trim();
      var row = wrapper.firstElementChild;
      container.querySelector("[data-formset-rows]").appendChild(row);
      total.value = index + 1;
      var first = row.querySelector("input, select, textarea");
      if (first) first.focus();
      container.dispatchEvent(new CustomEvent("formset:added", { bubbles: true, detail: { row: row } }));
      return;
    }
    var removeBtn = event.target.closest("[data-formset-remove]");
    if (removeBtn) {
      var rowEl = removeBtn.closest(".formset-row");
      var deleteBox = rowEl.querySelector('input[type=checkbox][name$="-DELETE"]');
      if (deleteBox) {
        deleteBox.checked = !deleteBox.checked;
        rowEl.classList.toggle("is-deleted", deleteBox.checked);
      }
      rowEl.dispatchEvent(new CustomEvent("formset:changed", { bubbles: true }));
    }
  });
})();
