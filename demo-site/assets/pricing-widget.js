/* Highlights the plan the visitor hovers over. Shipped with its source map still attached (deliberate fault). */
(function () {
  var rows = document.querySelectorAll('table.prices tbody tr');
  rows.forEach(function (row) {
    row.addEventListener('mouseenter', function () { row.style.background = '#f1f7f7'; });
    row.addEventListener('mouseleave', function () { row.style.background = ''; });
  });
})();
//# sourceMappingURL=pricing-widget.js.map
