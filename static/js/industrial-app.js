/**
 * Prima Bascol - Industrial Enterprise Application JS
 * High-Speed Keyboard UX, Live Calculations, Plate Lookup, Toast Notifications
 */

(function () {
  "use strict";

  // 1. Toast Notification Service
  window.showToast = function (message, type = "success") {
    let container = document.querySelector(".industrial-toast-container");
    if (!container) {
      container = document.createElement("div");
      container.className = "industrial-toast-container";
      document.body.appendChild(container);
    }

    const toast = document.createElement("div");
    toast.className = `industrial-toast toast-${type}`;

    let icon = "bi-check-circle-fill text-success";
    if (type === "danger") icon = "bi-x-circle-fill text-danger";
    if (type === "warning") icon = "bi-exclamation-triangle-fill text-warning";

    toast.innerHTML = `
      <i class="bi ${icon} fs-5"></i>
      <div class="flex-grow-1 font-medium">${message}</div>
      <button type="button" class="btn-close btn-close-sm" style="font-size: 0.7rem;"></button>
    `;

    toast.querySelector(".btn-close").addEventListener("click", () => {
      toast.remove();
    });

    container.appendChild(toast);
    setTimeout(() => {
      toast.style.opacity = "0";
      toast.style.transform = "translateX(-20px)";
      toast.style.transition = "all 0.3s ease";
      setTimeout(() => toast.remove(), 300);
    }, 4500);
  };

  // 2. Global Keyboard Shortcuts & Enter-Key Field Navigation
  function initKeyboardUX() {
    document.addEventListener("keydown", function (e) {
      // Ignore in standard modals or when textareas are actively editing
      const isTextarea = e.target.tagName === "TEXTAREA";

      // Enter key -> Move to next focusable form field
      if (e.key === "Enter" && !isTextarea && e.target.tagName === "INPUT" && e.target.type !== "submit") {
        const form = e.target.form;
        if (form && !e.target.classList.contains("no-enter-advance")) {
          e.preventDefault();
          const focusables = Array.from(
            form.querySelectorAll("input:not([type=hidden]):not([disabled]), select:not([disabled]), textarea:not([disabled])")
          );
          const idx = focusables.indexOf(e.target);
          if (idx > -1 && idx + 1 < focusables.length) {
            focusables[idx + 1].focus();
            if (focusables[idx + 1].select) focusables[idx + 1].select();
          }
        }
      }

      // Ctrl + Enter -> Submit / Complete Ticket
      if (e.ctrlKey && e.key === "Enter") {
        e.preventDefault();
        const completeBtn = document.getElementById("btn-complete-ticket") || document.querySelector("button[type=submit]");
        if (completeBtn) completeBtn.click();
      }

      // Ctrl + S -> Save Draft
      if (e.ctrlKey && (e.key === "s" || e.key === "S")) {
        e.preventDefault();
        const draftBtn = document.getElementById("btn-save-draft") || document.querySelector("button[name=submit_action][value=save]");
        if (draftBtn) draftBtn.click();
      }

      // F2 -> Focus License Plate
      if (e.key === "F2") {
        e.preventDefault();
        const p1 = document.getElementById("plate_part1") || document.getElementById("id_license_plate_display");
        if (p1) {
          p1.focus();
          if (p1.select) p1.select();
        }
      }

      // F4 -> Focus First / Active Weight Input
      if (e.key === "F4") {
        e.preventDefault();
        const wInput = document.getElementById("id_first_weight") || document.getElementById("id_second_weight");
        if (wInput) {
          wInput.focus();
          wInput.select();
        }
      }

      // F8 -> Save & Print
      if (e.key === "F8") {
        e.preventDefault();
        const printBtn = document.getElementById("btn-save-and-print") || document.querySelector("button[name=submit_action][value=save_and_print]");
        if (printBtn) printBtn.click();
      }

      // F11 / Operator Mode Toggle
      if (e.key === "F10") {
        e.preventDefault();
        toggleOperatorFullscreen();
      }
    });
  }

  // 3. Operator Fullscreen Focus Mode
  window.toggleOperatorFullscreen = function () {
    document.body.classList.toggle("operator-fullscreen");
    const isFull = document.body.classList.contains("operator-fullscreen");
    showToast(isFull ? "حالت تمام صفحه اپراتور فعال شد (F10 جهت خروج)" : "به حالت استاندارد بازگشتید.", "info");
  };

  // 4. Double Submit Prevention
  function initDoubleSubmitPrevention() {
    document.querySelectorAll("form").forEach((form) => {
      form.addEventListener("submit", function (e) {
        if (form.dataset.submitting === "true") {
          e.preventDefault();
          return;
        }
        form.dataset.submitting = "true";
        const submitBtn = form.querySelector("button[type=submit]");
        if (submitBtn) {
          submitBtn.classList.add("disabled");
          const originalText = submitBtn.innerHTML;
          submitBtn.innerHTML = `<span class="spinner-border spinner-border-sm me-1" role="status"></span> در حال ثبت...`;
          setTimeout(() => {
            submitBtn.classList.remove("disabled");
            submitBtn.innerHTML = originalText;
            form.dataset.submitting = "false";
          }, 6000);
        }
      });
    });
  }

  // 5. Iranian License Plate Widget & Live Plate Lookup
  function initPlateWidget() {
    const p1 = document.getElementById("plate_part1");
    const pLetter = document.getElementById("plate_letter");
    const p2 = document.getElementById("plate_part2");
    const pIran = document.getElementById("plate_iran");
    const pDisplay = document.getElementById("license_plate_display");
    const historyBox = document.getElementById("plate-history-banner");
    const openTicketWarning = document.getElementById("plate-open-ticket-alert");

    if (!p1 || !pLetter || !p2 || !pIran || !pDisplay) return;

    function syncPlateString() {
      const v1 = p1.value.trim();
      const vL = pLetter.value.trim();
      const v2 = p2.value.trim();
      const vI = pIran.value.trim();

      if (v1 && vL && v2 && vI) {
        pDisplay.value = `${v1} ${vL} ${v2} - ایران ${vI}`;
        triggerPlateLookup(pDisplay.value);
      } else {
        pDisplay.value = "";
        if (historyBox) historyBox.classList.add("d-none");
        if (openTicketWarning) openTicketWarning.classList.add("d-none");
      }
    }

    let lookupTimeout = null;
    function triggerPlateLookup(plateStr) {
      clearTimeout(lookupTimeout);
      lookupTimeout = setTimeout(() => {
        fetch(`/weighbridge/ajax/plate-lookup/?plate=${encodeURIComponent(plateStr)}`)
          .then((res) => res.json())
          .then((data) => {
            if (data.found) {
              if (historyBox) {
                historyBox.classList.remove("d-none");
                historyBox.innerHTML = `
                  <div class="d-flex align-items-center justify-content-between p-2 bg-info-subtle border border-info rounded">
                    <div>
                      <i class="bi bi-clock-history text-info me-1"></i>
                      <strong>سوابق خودرو:</strong> این خودرو قبلاً <strong>${data.trip_count} بار</strong> وارد مجموعه شده است. 
                      ${data.last_visit ? `<span class="text-muted ms-2">(آخرین ورود: ${data.last_visit})</span>` : ""}
                    </div>
                    ${data.driver_name ? `<span class="badge bg-primary">راننده متداول: ${data.driver_name}</span>` : ""}
                  </div>
                `;
              }

              // Auto-fill driver or vehicle type if empty
              const driverSelect = document.getElementById("id_driver");
              if (driverSelect && !driverSelect.value && data.driver_id) {
                driverSelect.value = data.driver_id;
              }
              const vehicleSelect = document.getElementById("id_vehicle");
              if (vehicleSelect && !vehicleSelect.value && data.vehicle_id) {
                vehicleSelect.value = data.vehicle_id;
              }
            } else {
              if (historyBox) historyBox.classList.add("d-none");
            }

            // Open Ticket Alert
            if (data.has_open_ticket && data.open_ticket) {
              if (openTicketWarning) {
                openTicketWarning.classList.remove("d-none");
                openTicketWarning.innerHTML = `
                  <div class="alert alert-warning border-warning shadow-sm d-flex align-items-center justify-content-between mb-0">
                    <div>
                      <i class="bi bi-exclamation-triangle-fill fs-4 text-warning me-2"></i>
                      <strong>هشدار قبض باز:</strong> این خودرو در حال حاضر یک قبض باز با شماره <strong>#${data.open_ticket.serial_number}</strong> در کارخانه دارد (ورود ساعت ${data.open_ticket.time} - کالا: ${data.open_ticket.product}).
                    </div>
                    <a href="/weighbridge/tickets/${data.open_ticket.id}/second-weight/" class="btn btn-warning btn-sm fw-bold px-3">
                      ثبت وزن دوم همین قبض
                    </a>
                  </div>
                `;
              }
            } else {
              if (openTicketWarning) openTicketWarning.classList.add("d-none");
            }
          })
          .catch((err) => console.log("Plate lookup error:", err));
      }, 350);
    }

    // Auto-advance between plate parts
    p1.addEventListener("input", function () {
      if (this.value.length >= 2) pLetter.focus();
      syncPlateString();
    });
    pLetter.addEventListener("change", function () {
      p2.focus();
      syncPlateString();
    });
    p2.addEventListener("input", function () {
      if (this.value.length >= 3) pIran.focus();
      syncPlateString();
    });
    pIran.addEventListener("input", function () {
      syncPlateString();
    });
  }

  // 6. Real-Time High-Precision Weighbridge Calculations
  function initLiveWeightCalculations() {
    const w1Input = document.getElementById("id_first_weight");
    const w2Input = document.getElementById("id_second_weight");
    const sentInput = document.getElementById("id_sent_weight");
    const lossPctInput = document.getElementById("id_loss_percent");
    const lossWeightInput = document.getElementById("id_loss_weight");
    const isLossOverridden = document.getElementById("id_is_loss_overridden");

    // Output Metric Elements
    const grossDisplay = document.getElementById("calc-gross-val");
    const tareDisplay = document.getElementById("calc-tare-val");
    const netDisplay = document.getElementById("calc-net-val");
    const netTonDisplay = document.getElementById("calc-net-ton");
    const lossDisplay = document.getElementById("calc-loss-val");
    const finalDisplay = document.getElementById("calc-final-val");
    const diffDisplay = document.getElementById("calc-diff-val");
    const diffBadge = document.getElementById("calc-diff-badge");
    const diffAlert = document.getElementById("tolerance-warning-alert");

    // Sticky Summary Elements
    const stickyGross = document.getElementById("sticky-gross");
    const stickyTare = document.getElementById("sticky-tare");
    const stickyNet = document.getElementById("sticky-net");
    const stickyLoss = document.getElementById("sticky-loss");
    const stickyFinal = document.getElementById("sticky-final");

    function parseNum(val) {
      if (!val) return 0;
      const clean = String(val).replace(/,/g, "").trim();
      const n = parseFloat(clean);
      return isNaN(n) ? 0 : n;
    }

    function formatKg(num) {
      if (num === null || num === undefined || isNaN(num)) return "0";
      const rounded = Math.round(num * 100) / 100;
      return rounded.toLocaleString("fa-IR", {
        minimumFractionDigits: 0,
        maximumFractionDigits: 2,
      });
    }

    function calculateAll() {
      const w1 = parseNum(w1Input ? w1Input.value : 0);
      const hasW2 = w2Input && w2Input.value.trim() !== "";
      const w2 = hasW2 ? parseNum(w2Input.value) : null;
      const sent = parseNum(sentInput ? sentInput.value : 0);
      const lossPct = parseNum(lossPctInput ? lossPctInput.value : 0);

      let gross = w1;
      let tare = 0;
      let net = 0;

      if (hasW2 && w2 !== null) {
        gross = Math.max(w1, w2);
        tare = Math.min(w1, w2);
        net = gross - tare;
      } else {
        gross = w1;
        tare = 0;
        net = 0;
      }

      let lossKg = 0;
      if (isLossOverridden && isLossOverridden.checked && lossWeightInput && lossWeightInput.value) {
        lossKg = parseNum(lossWeightInput.value);
      } else {
        if (net > 0 && lossPct > 0) {
          lossKg = (net * lossPct) / 100;
        }
        if (lossWeightInput && (!isLossOverridden || !isLossOverridden.checked)) {
          lossWeightInput.value = lossKg > 0 ? Math.round(lossKg * 100) / 100 : 0;
        }
      }

      const final = Math.max(0, net - lossKg);
      const diff = sent > 0 && net > 0 ? net - sent : 0;
      const diffPct = sent > 0 && net > 0 ? ((diff / sent) * 100).toFixed(2) : "0.00";

      // Update Main Calculation Display
      if (grossDisplay) grossDisplay.textContent = formatKg(gross);
      if (tareDisplay) tareDisplay.textContent = formatKg(tare);
      if (netDisplay) netDisplay.textContent = formatKg(net);
      if (netTonDisplay) netTonDisplay.textContent = `≈ ${(net / 1000).toFixed(2)} تن`;
      if (lossDisplay) lossDisplay.textContent = formatKg(lossKg);
      if (finalDisplay) finalDisplay.textContent = formatKg(final);

      // Sent Weight Variance
      if (diffDisplay) {
        const sign = diff > 0 ? "+" : "";
        diffDisplay.textContent = `${sign}${formatKg(diff)} Kg (${sign}${diffPct}%)`;
      }

      const maxTol = parseFloat(document.body.dataset.maxToleranceKg || 50);
      const isExceeded = sent > 0 && net > 0 && Math.abs(diff) > maxTol;

      if (diffBadge) {
        if (net === 0 || sent === 0) {
          diffBadge.className = "badge bg-secondary";
          diffBadge.textContent = "در انتظار محاسبه";
        } else if (isExceeded) {
          diffBadge.className = "badge bg-danger";
          diffBadge.textContent = "مغایرت غیرمجاز";
        } else {
          diffBadge.className = "badge bg-success";
          diffBadge.textContent = "مجاز";
        }
      }

      if (diffAlert) {
        if (isExceeded) {
          diffAlert.classList.remove("d-none");
          diffAlert.innerHTML = `<i class="bi bi-exclamation-octagon-fill me-1"></i> هشدار: اختلاف وزن باسکول با بارنامه مبدأ (${formatKg(Math.abs(diff))} Kg) بیش از حد مجاز استاندارد (${maxTol} Kg) است!`;
        } else {
          diffAlert.classList.add("d-none");
        }
      }

      // Update Sticky Summary Panel
      if (stickyGross) stickyGross.textContent = formatKg(gross);
      if (stickyTare) stickyTare.textContent = formatKg(tare);
      if (stickyNet) stickyNet.textContent = formatKg(net);
      if (stickyLoss) stickyLoss.textContent = formatKg(lossKg);
      if (stickyFinal) stickyFinal.textContent = formatKg(final);
    }

    [w1Input, w2Input, sentInput, lossPctInput, lossWeightInput].forEach((el) => {
      if (el) {
        el.addEventListener("input", calculateAll);
        el.addEventListener("change", calculateAll);
      }
    });

    if (isLossOverridden) {
      isLossOverridden.addEventListener("change", function () {
        if (lossWeightInput) {
          lossWeightInput.readOnly = !this.checked;
          if (this.checked) lossWeightInput.focus();
        }
        calculateAll();
      });
    }

    calculateAll();
  }

  // 7. Table Density Toggle
  window.setTableDensity = function (density) {
    const table = document.querySelector(".industrial-table");
    if (!table) return;
    if (density === "compact") {
      table.classList.add("table-density-compact");
    } else {
      table.classList.remove("table-density-compact");
    }
    localStorage.setItem("bascol_table_density", density);
  };

  // 8. Live Clock in Header
  function initLiveClock() {
    const clockEl = document.getElementById("header-live-clock");
    if (!clockEl) return;
    function tick() {
      const now = new Date();
      const h = String(now.getHours()).padStart(2, "0");
      const m = String(now.getMinutes()).padStart(2, "0");
      const s = String(now.getSeconds()).padStart(2, "0");
      clockEl.textContent = `${h}:${m}:${s}`;
    }
    tick();
    setInterval(tick, 1000);
  }

  // 9. Dynamic Active Navigation Indicator
  function initSidebarActiveNav() {
    const currentPath = window.location.pathname;
    const currentSearch = window.location.search;
    const fullCurrentUrl = currentPath + currentSearch;

    const navLinks = document.querySelectorAll("#app-sidebar .sidebar-nav a.nav-link");
    let matchedLink = null;
    let bestMatchScore = 0;

    navLinks.forEach((link) => {
      const href = link.getAttribute("href");
      if (!href || href === "#" || href.startsWith("javascript:")) return;

      // Exact match with query params (e.g. ?status=waiting_second)
      if (href === fullCurrentUrl) {
        matchedLink = link;
        bestMatchScore = 100;
      } else if (href === currentPath && bestMatchScore < 50) {
        matchedLink = link;
        bestMatchScore = 50;
      } else if (currentPath.startsWith(href) && href !== "/" && href.length > 2 && bestMatchScore < 20) {
        matchedLink = link;
        bestMatchScore = 20;
      }
    });

    if (matchedLink) {
      const parentCollapse = matchedLink.closest(".collapse");
      if (parentCollapse) {
        parentCollapse.querySelectorAll(".nav-link.active").forEach((el) => {
          if (el !== matchedLink) el.classList.remove("active");
        });
        parentCollapse.classList.add("show");
        const toggleBtn = document.querySelector(`[href="#${parentCollapse.id}"]`);
        if (toggleBtn) {
          toggleBtn.classList.add("active");
          toggleBtn.setAttribute("aria-expanded", "true");
        }
      }
      matchedLink.classList.add("active");
    }
  }

  // DOM Ready Initializations
  document.addEventListener("DOMContentLoaded", function () {
    initKeyboardUX();
    initDoubleSubmitPrevention();
    initPlateWidget();
    initLiveWeightCalculations();
    initLiveClock();
    initSidebarActiveNav();

    // Restore density preference
    const savedDensity = localStorage.getItem("bascol_table_density");
    if (savedDensity) setTableDensity(savedDensity);
  });
})();
