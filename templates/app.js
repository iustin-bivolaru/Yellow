/* Yellow: category filter and service worker registration. Without JS everything stays visible. */
(function () {
  "use strict";
  var script = document.currentScript;
  var bar = document.getElementById("cats");
  var feed = document.getElementById("feed");
  if (bar && feed) {
    bar.hidden = false;
    var cards = Array.prototype.slice.call(feed.querySelectorAll(".card"));
    var buttons = Array.prototype.slice.call(bar.querySelectorAll("button"));
    bar.addEventListener("click", function (event) {
      var btn = event.target.closest("button");
      if (!btn) return;
      var cat = btn.getAttribute("data-cat");
      buttons.forEach(function (b) {
        b.setAttribute("aria-pressed", b === btn ? "true" : "false");
      });
      cards.forEach(function (card) {
        card.hidden = cat !== "" && card.getAttribute("data-cat") !== cat;
      });
    });
  }
  if ("serviceWorker" in navigator && script && script.src) {
    window.addEventListener("load", function () {
      navigator.serviceWorker.register(new URL("sw.js", script.src).href).catch(function () {});
    });
  }
})();
