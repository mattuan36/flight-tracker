/* Price chart inspection: hover or tap a point for its exact date and fare.
 *
 * The check points carry their data in data-* attributes, so this file never
 * needs to know how the chart was scaled. Clicking pins a tooltip; Escape or a
 * click on the background clears it. Arrow keys walk the points from the SVG.
 */
(function () {
  "use strict";

  var chart = document.querySelector("[data-price-chart]");
  if (!chart) {
    return;
  }

  var svg = chart.querySelector("svg");
  var tip = chart.querySelector(".chart-tip");
  var cursor = chart.querySelector(".chart-cursor");
  var points = Array.prototype.slice.call(chart.querySelectorAll(".chart-hit"));
  if (!svg || !tip || points.length === 0) {
    return;
  }

  var pinned = null;
  var active = null;

  function show(point, pin) {
    active = point;
    tip.textContent = "";

    var price = document.createElement("strong");
    price.textContent = point.dataset.price;
    var when = document.createElement("span");
    when.textContent = point.dataset.when;
    tip.append(price, when);
    tip.hidden = false;

    var box = chart.getBoundingClientRect();
    var rect = point.getBoundingClientRect();
    var half = tip.offsetWidth / 2;
    var centre = rect.left + rect.width / 2 - box.left;
    var left = Math.min(Math.max(centre, half + 4), box.width - half - 4);

    tip.style.left = left + "px";
    tip.style.top = Math.max(rect.top - box.top - 8, tip.offsetHeight + 4) + "px";

    if (cursor) {
      cursor.setAttribute("cx", point.dataset.x);
      cursor.setAttribute("cy", point.dataset.y);
      cursor.removeAttribute("hidden");
    }

    if (pin) {
      pinned = point;
    }
  }

  function hide() {
    active = null;
    tip.hidden = true;
    if (cursor) {
      cursor.setAttribute("hidden", "");
    }
  }

  points.forEach(function (point) {
    point.addEventListener("mouseenter", function () {
      show(point);
    });
    point.addEventListener("focus", function () {
      show(point);
    });
    point.addEventListener("click", function (event) {
      event.stopPropagation();
      if (pinned === point) {
        pinned = null;
        hide();
        return;
      }
      show(point, true);
    });
  });

  chart.addEventListener("mouseleave", function () {
    if (pinned) {
      show(pinned);
    } else {
      hide();
    }
  });

  chart.addEventListener("click", function (event) {
    if (!event.target.closest(".chart-hit")) {
      pinned = null;
      hide();
    }
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && pinned) {
      pinned = null;
      hide();
    }
  });

  svg.addEventListener("keydown", function (event) {
    if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") {
      return;
    }
    event.preventDefault();
    var step = event.key === "ArrowRight" ? 1 : -1;
    var index = active ? points.indexOf(active) : -1;
    if (index === -1) {
      index = step > 0 ? -1 : points.length;
    }
    var next = Math.max(0, Math.min(points.length - 1, index + step));
    points[next].focus();
  });
})();
