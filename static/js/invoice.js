/* Live invoice totals preview. Uses integer cents to avoid floating-point drift;
   the authoritative calculation is done on the server with Decimal. */
(function () {
  "use strict";
  var form = document.querySelector("[data-invoice-form]");
  if (!form) return;
  var currency = form.dataset.currency || "";

  function cents(value) {
    var n = parseFloat(String(value).replace(/,/g, ""));
    return isFinite(n) ? Math.round(n * 100) : 0;
  }
  function fmt(c) {
    var sign = c < 0 ? "-" : "";
    c = Math.abs(c);
    return sign + currency + (Math.floor(c / 100)).toLocaleString() + "." + String(c % 100).padStart(2, "0");
  }

  function recalc() {
    var subtotal = 0;
    form.querySelectorAll(".formset-row").forEach(function (row) {
      var del = row.querySelector('input[name$="-DELETE"]');
      var qty = row.querySelector('input[name$="-quantity"]');
      var price = row.querySelector('input[name$="-unit_price"]');
      var lineEl = row.querySelector("[data-line-total]");
      var line = 0;
      if (qty && price && !(del && del.checked)) {
        line = Math.round(cents(qty.value) * cents(price.value) / 100);
        subtotal += line;
      }
      if (lineEl) lineEl.textContent = fmt(line);
    });
    var discount = cents((form.querySelector("#id_discount_amount") || {}).value || 0);
    form.querySelector("[data-subtotal]").textContent = fmt(subtotal);
    form.querySelector("[data-discount]").textContent = fmt(discount);
    var total = Math.max(subtotal - discount, 0);
    form.querySelector("[data-total]").textContent = fmt(total);
    var warn = form.querySelector("[data-discount-warning]");
    if (warn) warn.classList.toggle("d-none", discount <= subtotal);
  }

  form.addEventListener("input", recalc);
  form.addEventListener("change", recalc);
  form.addEventListener("formset:added", recalc);
  form.addEventListener("formset:changed", recalc);
  recalc();
})();
