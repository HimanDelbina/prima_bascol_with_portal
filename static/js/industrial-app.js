/**
 * Prima Bascol - Industrial Enterprise Application JS
 * High-Speed Keyboard UX, Live Calculations, Plate Lookup, Toast Notifications
 */

(function () {
  "use strict";

  function escapeHtml(value) {
    const node = document.createElement("span");
    node.textContent = String(value ?? "");
    return node.innerHTML;
  }

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
      <div class="flex-grow-1 font-medium">${escapeHtml(message)}</div>
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

  // Helper to block or unblock all ticket submission buttons
  window.setPlateBlockedState = function (isBlocked, blockReason = "") {
    const finalBtn = document.getElementById("btn-open-confirm-modal");
    const completeBtn = document.getElementById("btn-complete-ticket");
    const draftBtn = document.getElementById("btn-save-draft");
    const printBtn = document.getElementById("btn-save-and-print");
    const submitBtns = Array.from(document.querySelectorAll("button[type=submit]"));
    const allActionBtns = Array.from(new Set([finalBtn, completeBtn, draftBtn, printBtn, ...submitBtns].filter(Boolean)));

    if (isBlocked) {
      document.body.dataset.plateBlocked = "true";
      allActionBtns.forEach((btn) => {
        btn.disabled = true;
        btn.classList.add("disabled");
        btn.setAttribute("title", `پلاک در لیست سیاه مسدود است: ${blockReason || "بارگیری ممنوع"}`);
      });
      if (finalBtn) {
        finalBtn.classList.remove("btn-success");
        finalBtn.classList.add("btn-danger");
        finalBtn.innerHTML = `<i class="bi bi-ban me-1"></i> پلاک مسدود است (بارگیری ممنوع)`;
      }
    } else {
      document.body.dataset.plateBlocked = "false";
      allActionBtns.forEach((btn) => {
        btn.disabled = false;
        btn.classList.remove("disabled");
        btn.removeAttribute("title");
      });
      if (finalBtn) {
        finalBtn.classList.remove("btn-danger");
        finalBtn.classList.add("btn-success");
        finalBtn.innerHTML = `<i class="bi bi-check2-circle me-1"></i> ثبت و تکمیل نهایی باسکول <span class="key-hint-badge bg-white text-dark">Ctrl + Enter</span>`;
      }
    }
  };

  // 1b. Disable Mouse Wheel Scroll on Number Inputs & Numeric Form Fields
  function initDisableWheelOnInputs() {
    function isNumericInput(el) {
      if (!el || el.tagName !== "INPUT") return false;
      const type = (el.type || el.getAttribute("type") || "").toLowerCase();
      const inputMode = (el.getAttribute("inputmode") || "").toLowerCase();
      return (
        type === "number" ||
        inputMode === "numeric" ||
        inputMode === "decimal" ||
        el.classList.contains("no-wheel") ||
        el.classList.contains("weight-input") ||
        el.classList.contains("iran-plate-part") ||
        (el.id && (el.id.includes("weight") || el.id.includes("loss") || el.id.includes("freight") || el.id.includes("count") || el.id.includes("plate"))) ||
        (el.name && (el.name.includes("weight") || el.name.includes("loss") || el.name.includes("freight") || el.name.includes("count") || el.name.includes("plate")))
      );
    }

    // Capture wheel events on window with passive: false to cancel value mutation
    window.addEventListener(
      "wheel",
      function (e) {
        const target = e.target;
        if (isNumericInput(target)) {
          // Block browser's native stepUp / stepDown
          e.preventDefault();

          // Smoothly forward scroll to containing scrollable element or window
          const scrollContainer =
            target.closest(
              ".modal.show .modal-body, .modal.show, .overflow-auto, .overflow-y-auto"
            ) || window;

          let dy = e.deltaY;
          let dx = e.deltaX;
          if (e.deltaMode === 1) {
            dy *= 33;
            dx *= 33;
          } else if (e.deltaMode === 2) {
            dy *= window.innerHeight;
            dx *= window.innerWidth;
          }

          if (scrollContainer === window) {
            window.scrollBy({
              top: dy,
              left: dx,
              behavior: "auto",
            });
          } else {
            scrollContainer.scrollBy({
              top: dy,
              left: dx,
              behavior: "auto",
            });
          }
        }
      },
      { passive: false }
    );

    // Also attach directly to all existing numeric inputs
    function attachInputPreventWheel(el) {
      if (!el || el.dataset.wheelPreventAttached) return;
      el.dataset.wheelPreventAttached = "true";
      el.addEventListener(
        "wheel",
        function (e) {
          e.preventDefault();
        },
        { passive: false }
      );
    }

    document
      .querySelectorAll('input[type="number"], input[inputmode="numeric"], input[inputmode="decimal"], .weight-input, .iran-plate-part')
      .forEach(attachInputPreventWheel);

    // Dynamic support for any newly added inputs (e.g., in quick-add modals)
    if (window.MutationObserver) {
      const observer = new MutationObserver(function (mutations) {
        mutations.forEach(function (mutation) {
          mutation.addedNodes.forEach(function (node) {
            if (node.nodeType === 1) {
              if (isNumericInput(node)) {
                attachInputPreventWheel(node);
              }
              if (node.querySelectorAll) {
                node
                  .querySelectorAll('input[type="number"], input[inputmode="numeric"], input[inputmode="decimal"], .weight-input, .iran-plate-part')
                  .forEach(attachInputPreventWheel);
              }
            }
          });
        });
      });
      observer.observe(document.documentElement || document.body, { childList: true, subtree: true });
    }
  }

  // 2. Global Keyboard Shortcuts & Enter-Key Field Navigation
  function initKeyboardUX() {
    document.addEventListener("keydown", function (e) {
      // Ignore in standard modals or when textareas are actively editing
      const isTextarea = e.target.tagName === "TEXTAREA";

      // Enter key -> Move to next focusable form field
      if (e.key === "Enter" && !isTextarea && (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") && e.target.type !== "submit") {
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
        if (document.body.dataset.plateBlocked === "true") {
          window.showToast("خطا: این پلاک در لیست سیاه مسدود شده و امکان بارگیری یا صدور قبض ندارد.", "danger");
          return;
        }
        const completeBtn = document.getElementById("btn-complete-ticket") || document.querySelector("button[type=submit]");
        if (completeBtn && !completeBtn.disabled) completeBtn.click();
      }

      // Ctrl + S -> Save Draft
      if (e.ctrlKey && (e.key === "s" || e.key === "S")) {
        e.preventDefault();
        if (document.body.dataset.plateBlocked === "true") {
          window.showToast("خطا: این پلاک در لیست سیاه مسدود شده است.", "danger");
          return;
        }
        const draftBtn = document.getElementById("btn-save-draft") || document.querySelector("button[name=submit_action][value=save]");
        if (draftBtn && !draftBtn.disabled) draftBtn.click();
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
        if (document.body.dataset.plateBlocked === "true") {
          window.showToast("خطا: این پلاک در لیست سیاه مسدود شده است.", "danger");
          return;
        }
        const printBtn = document.getElementById("btn-save-and-print") || document.querySelector("button[name=submit_action][value=save_and_print]");
        if (printBtn && !printBtn.disabled) printBtn.click();
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

  // 4. Double Submit Prevention & Blocked Plate Protection
  function initDoubleSubmitPrevention() {
    document.querySelectorAll("form").forEach((form) => {
      form.addEventListener("submit", function (e) {
        if (document.body.dataset.plateBlocked === "true") {
          e.preventDefault();
          e.stopPropagation();
          window.showToast("⛔ خطا: این پلاک در لیست سیاه مسدود است و امکان بارگیری یا صدور قبض ندارد.", "danger");
          return false;
        }
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

  // Helper: Convert Persian/Arabic digits to English digits
  function toEnDigits(str) {
    if (!str) return "";
    return String(str)
      .replace(/[۰-۹]/g, (d) => "۰۱۲۳۴۵۶۷۸۹".indexOf(d))
      .replace(/[٠-٩]/g, (d) => "٠١٢٣٤٥٦٧٨٩".indexOf(d));
  }
  window.toEnDigits = toEnDigits;

  // 5. Iranian License Plate Widget & Live Plate Lookup (Auto-Fill Vehicle & Driver)
  function initPlateWidget() {
    const p1 = document.getElementById("plate_part1") || document.getElementById("id_plate_part1");
    const pLetter = document.getElementById("plate_letter") || document.getElementById("id_plate_letter");
    const p2 = document.getElementById("plate_part2") || document.getElementById("id_plate_part2");
    const pIran = document.getElementById("plate_iran") || document.getElementById("id_plate_iran");
    const pDisplay =
      document.getElementById("license_plate_display") ||
      document.getElementById("id_license_plate_display") ||
      document.getElementById("id_plate_display") ||
      document.querySelector("[name='license_plate_display']");
    const historyBox = document.getElementById("plate-history-banner");
    const openTicketWarning = document.getElementById("plate-open-ticket-alert");
    const isTicketPage = !!(document.getElementById("ticket-create-form") || document.getElementById("id_first_weight") || historyBox);

    if (!p1 || !pLetter || !p2 || !pIran) return;

    function flashAutoFillField(el) {
      if (!el) return;
      el.classList.add("auto-filled-success");
      setTimeout(() => {
        el.classList.remove("auto-filled-success");
      }, 2500);
    }

    let lastLookedUpPlate = "";
    let lookupTimeout = null;

    function syncPlateString() {
      const v1 = toEnDigits(p1.value.trim()).replace(/[^0-9]/g, "");
      const vL = pLetter.value.trim();
      const v2 = toEnDigits(p2.value.trim()).replace(/[^0-9]/g, "");
      const vI = toEnDigits(pIran.value.trim()).replace(/[^0-9]/g, "");

      let fullPlate = "";
      if (v1 && vL && v2 && vI) {
        fullPlate = `${v1} ${vL} ${v2} - ایران ${vI}`;
      }

      // Update all display targets
      const targets = document.querySelectorAll(
        "[name='license_plate_display'], #license_plate_display, #id_license_plate_display, #id_plate_display"
      );
      targets.forEach((el) => {
        if (el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA")) {
          if (fullPlate) {
            el.value = fullPlate;
          } else if (v1 || vL || v2 || vI) {
            el.value = `${v1 || "--"} ${vL || "-"} ${v2 || "---"} - ایران ${vI || "--"}`;
          } else {
            el.value = "";
          }
        }
      });

      if (isTicketPage) {
        if (fullPlate) {
          triggerPlateLookup(fullPlate);
        } else {
          lastLookedUpPlate = "";
          if (typeof window.setPlateBlockedState === "function") {
            window.setPlateBlockedState(false);
          }
          if (historyBox) historyBox.classList.add("d-none");
          if (openTicketWarning) openTicketWarning.classList.add("d-none");
        }
      }
    }

    function triggerPlateLookup(plateStr) {
      if (!plateStr || plateStr === lastLookedUpPlate) return;
      clearTimeout(lookupTimeout);
      lookupTimeout = setTimeout(() => {
        lastLookedUpPlate = plateStr;
        fetch(`/weighbridge/ajax/plate-lookup/?plate=${encodeURIComponent(plateStr)}`)
          .then((res) => res.json())
          .then((data) => {
            // 0. Blacklist / Blocked Plate Warning
            if (data.is_blocked) {
              if (typeof window.setPlateBlockedState === "function") {
                window.setPlateBlockedState(true, data.block_reason);
              }
              if (historyBox) {
                historyBox.classList.remove("d-none");
                historyBox.innerHTML = `
                  <div class="alert alert-danger border-danger shadow-sm d-flex flex-wrap align-items-center justify-content-between p-3 rounded-2 mb-3">
                    <div class="d-flex align-items-center gap-3">
                      <i class="bi bi-slash-circle-fill text-danger fs-2"></i>
                      <div>
                        <strong class="text-danger fs-6 d-block mb-1">⛔ پلاک در لیست سیاه مسدود شده است!</strong>
                        <span class="small text-dark d-block">این خودرو مسدود شده و امکان بارگیری یا صدور قبض باسکول برای آن وجود ندارد.</span>
                        <div class="small text-danger fw-bold mt-1">علت مسدودی: ${escapeHtml(data.block_reason)}</div>
                        ${data.blocked_by ? `<div class="small text-muted mt-1">ثبت مسدودی توسط: ${escapeHtml(data.blocked_by)} ${data.blocked_at ? `(${escapeHtml(data.blocked_at)})` : ''}</div>` : ''}
                      </div>
                    </div>
                    <span class="badge bg-danger text-white px-3 py-2 fs-6 mt-2 mt-md-0"><i class="bi bi-ban me-1"></i>بارگیری ممنوع</span>
                  </div>
                `;
              }
              if (typeof window.showToast === "function") {
                window.showToast("هشدار: این پلاک در لیست سیاه مسدود است! دکمه‌های ثبت غیرفعال شدند.", "danger");
              }
              return;
            }

            // Unblock buttons when a valid, non-blocked plate is checked
            if (typeof window.setPlateBlockedState === "function") {
              window.setPlateBlockedState(false);
            }

            // Indicator badge update
            const indicator = document.getElementById("plate-autofill-indicator");
            if (indicator) {
              if (data.is_autofill_enabled) {
                indicator.className = "badge bg-primary text-white border border-primary small fw-normal d-none d-sm-inline";
                indicator.innerHTML = '<i class="bi bi-lightning-charge-fill me-1"></i>پلاک تکمیل خودکار (اطلاعات آخرین ورود)';
              } else {
                indicator.className = "badge bg-light text-muted border small fw-normal d-none d-sm-inline";
                indicator.innerHTML = '<i class="bi bi-magic text-primary me-1"></i>تکمیل خودکار سوابق تکراری فعال است';
              }
            }

            if (data.found || data.is_duplicate || data.autofill_data) {
              const af = data.autofill_data;

              // Helper: Robust select matcher by ID and by text/option label
              const setSelectField = (selector, idVal, nameVal) => {
                const el = document.querySelector(selector);
                if (!el) return false;
                let matched = false;
                if (idVal !== null && idVal !== undefined && idVal !== "") {
                  el.value = String(idVal);
                  if (el.value === String(idVal)) {
                    matched = true;
                  }
                }
                if (!matched && nameVal) {
                  const target = String(nameVal).trim().toLowerCase();
                  for (let opt of el.options) {
                    const optText = (opt.text || "").trim().toLowerCase();
                    if (optText === target || (optText && optText.includes(target)) || target.includes(optText)) {
                      el.value = opt.value;
                      matched = true;
                      break;
                    }
                  }
                }
                if (matched) {
                  el.dataset.autofilled = "true";
                  flashAutoFillField(el);
                  el.dispatchEvent(new Event("change", { bubbles: true }));
                }
                return matched;
              };

              // Helper: Robust text/number input setter
              const setInputField = (selector, val) => {
                const el = document.querySelector(selector);
                if (!el) return false;
                if (val !== null && val !== undefined && val !== "") {
                  el.value = String(val);
                  el.dataset.autofilled = "true";
                  flashAutoFillField(el);
                  el.dispatchEvent(new Event("input", { bubbles: true }));
                  return true;
                }
                return false;
              };

              // 1. History & Recognition Banner
              if (historyBox) {
                historyBox.classList.remove("d-none");
                if (af) {
                  historyBox.innerHTML = `
                    <div class="alert alert-primary border-primary bg-primary-subtle shadow-sm d-flex flex-wrap align-items-center justify-content-between p-2 px-3 rounded-3 mb-3">
                      <div class="d-flex align-items-center gap-2">
                        <i class="bi bi-magic text-primary fs-3"></i>
                        <div>
                          <strong class="text-primary-emphasis">تکمیل خودکار اطلاعات از آخرین ورود فعال شد:</strong>
                          <span class="small text-dark ms-1">نوع عملیات، طرف حساب، کالا، مسیر (مبدأ/مقصد)، جایگاه تخلیه و راننده از آخرین قبض (<strong>#${escapeHtml(af.last_ticket_serial)}</strong> مورخ ${escapeHtml(af.last_ticket_date)}) پر شدند.</span>
                          <div class="small text-danger fw-bold mt-1"><i class="bi bi-shield-lock me-1"></i>فیلدهای وزن جهت ثبت دقیق توزین توسط اپراتور خالی نگه داشته شده‌اند.</div>
                        </div>
                      </div>
                      <div class="d-flex align-items-center gap-1 mt-1 mt-md-0">
                        <span class="badge bg-primary text-white px-2 py-1"><i class="bi bi-lightning-charge-fill me-1"></i>تکمیل خودکار از آخرین قبض</span>
                      </div>
                    </div>
                  `;
                } else {
                  historyBox.innerHTML = `
                    <div class="alert alert-success border-success bg-success-subtle shadow-sm d-flex flex-wrap align-items-center justify-content-between p-2 px-3 rounded-3 mb-3">
                      <div class="d-flex align-items-center gap-2">
                        <i class="bi bi-patch-check-fill text-success fs-5"></i>
                        <div>
                          <strong class="text-success-emphasis">پلاک شناسایی شد (خودرو دارای سابقه):</strong>
                          <span class="small text-dark ms-1">مشخصات خودرو و راننده به‌طور خودکار درج شد.</span>
                          ${data.trip_count ? `<span class="badge bg-success text-white ms-2 font-monospace">${data.trip_count} بار ورود قبلی</span>` : ""}
                          ${data.last_visit ? `<span class="small text-muted ms-2">(آخرین تردد: ${escapeHtml(data.last_visit)})</span>` : ""}
                        </div>
                      </div>
                      <div class="d-flex align-items-center gap-2 mt-1 mt-md-0">
                        ${data.driver_name ? `<span class="badge bg-primary px-2 py-1"><i class="bi bi-person-fill me-1"></i>${escapeHtml(data.driver_name)}</span>` : ""}
                        ${data.driver_mobile ? `<span class="badge bg-secondary px-2 py-1 font-monospace" dir="ltr"><i class="bi bi-telephone-fill me-1"></i>${escapeHtml(data.driver_mobile)}</span>` : ""}
                        ${data.vehicle_type_name ? `<span class="badge bg-dark px-2 py-1"><i class="bi bi-truck me-1"></i>${escapeHtml(data.vehicle_type_name)}</span>` : ""}
                      </div>
                    </div>
                  `;
                }
              }

              // 2. Driver Name & Mobile
              setInputField("#id_driver_name_custom, [name='driver_name_custom']", (af ? af.driver_name : null) || data.driver_name);
              setInputField("#id_driver_mobile_custom, [name='driver_mobile_custom']", (af ? af.driver_mobile : null) || data.driver_mobile);

              // 3. Vehicle Type
              setSelectField("#id_vehicle_type, [name='vehicle_type']", (af ? af.vehicle_type_id : null) || data.vehicle_type_id, (af ? af.vehicle_type_name : null) || data.vehicle_type_name);
              setInputField("#id_vehicle_type_custom, [name='vehicle_type_custom']", (af ? af.vehicle_type_custom : null) || data.vehicle_type_custom);

              // 4. Driver & Vehicle FK
              const driverFk = document.querySelector("#id_driver, [name='driver']");
              if (driverFk) driverFk.value = (af && af.driver_id) || data.driver_id || "";
              const vehicleFk = document.querySelector("#id_vehicle, [name='vehicle']");
              if (vehicleFk) vehicleFk.value = data.vehicle_id || "";

              // 5. Cargo, Operation & Logistics Fields (Only when autofill_data exists)
              if (af) {
                // Operation Type
                setSelectField("#id_operation_type, [name='operation_type']", af.operation_type_id, af.operation_type_name);

                // Party
                setSelectField("#id_party, [name='party']", af.party_id, af.party_name);

                // Product
                setSelectField("#id_product, [name='product']", af.product_id, af.product_name);

                // Origin
                setSelectField("#id_origin, [name='origin']", af.origin_id, af.origin_name);

                // Destination
                setSelectField("#id_destination, [name='destination']", af.destination_id, af.destination_name);

                // Unload Location
                setSelectField("#id_unload_location, [name='unload_location']", af.unload_location_id, af.unload_location_name);

                // Freight Amount
                setInputField("#id_freight_amount, [name='freight_amount']", af.freight_amount);

                // Load Count & Ingot Count
                setInputField("#id_load_count, [name='load_count']", af.load_count);
                setInputField("#id_ingot_count, [name='ingot_count']", af.ingot_count);

                // Loss Type & Percent
                setSelectField("#id_loss_type, [name='loss_type']", af.loss_type_id, af.loss_type_name);
                setInputField("#id_loss_percent, [name='loss_percent']", af.loss_percent);

                // Weight Mode
                setSelectField("#id_weight_mode, [name='weight_mode']", af.weight_mode);

                // Notification Toast
                if (typeof window.showToast === "function") {
                  window.showToast(`تمام اطلاعات از آخرین قبض (#${escapeHtml(af.last_ticket_serial)}) بارگذاری شد (فیلدهای وزن خالی ماندند).`, "primary");
                }
              } else {
                if (typeof window.showToast === "function") {
                  window.showToast("مشخصات خودرو و راننده از سوابق پلاک بارگذاری شد.", "success");
                }
              }
            } else {
              // Plate is NOT duplicate (New Vehicle / Driver)
              if (historyBox) {
                historyBox.classList.remove("d-none");
                historyBox.innerHTML = `
                  <div class="alert alert-info border-info bg-info-subtle shadow-sm d-flex flex-wrap align-items-center justify-content-between p-2 px-3 rounded-3 mb-3">
                    <div class="d-flex align-items-center gap-2">
                      <i class="bi bi-info-circle-fill text-info fs-5"></i>
                      <div>
                        <strong class="text-info-emphasis">پلاک جدید (شناسایی‌نشده):</strong>
                        <span class="small text-dark ms-1">این خودرو در سیستم ثبت نیست؛ با ثبت این قبض، مشخصات خودرو و راننده به‌طور خودکار در سامانه ثبت خواهند شد.</span>
                      </div>
                    </div>
                    <span class="badge bg-primary text-white px-2 py-1"><i class="bi bi-magic me-1"></i>ثبت خودکار فعال است</span>
                  </div>
                `;
              }

              // Clear fields that were previously auto-filled from an old plate
              const clearAutoFilled = (id, defaultValue = "") => {
                const el = document.getElementById(id);
                if (el && el.dataset.autofilled === "true") {
                  el.value = defaultValue;
                  delete el.dataset.autofilled;
                  el.dispatchEvent(new Event(el.tagName === "SELECT" ? "change" : "input", { bubbles: true }));
                }
              };
              clearAutoFilled("id_driver_name_custom");
              clearAutoFilled("id_driver_mobile_custom");
              clearAutoFilled("id_vehicle_type");
              clearAutoFilled("id_operation_type");
              clearAutoFilled("id_party");
              clearAutoFilled("id_product");
              clearAutoFilled("id_origin");
              clearAutoFilled("id_destination");
              clearAutoFilled("id_unload_location");
              clearAutoFilled("id_freight_amount");
              clearAutoFilled("id_ingot_count");
              clearAutoFilled("id_loss_type");
              clearAutoFilled("id_loss_percent");

              const driverFk = document.getElementById("id_driver");
              if (driverFk) driverFk.value = "";
              const vehicleFk = document.getElementById("id_vehicle");
              if (vehicleFk) vehicleFk.value = "";
            }

            // Open Ticket Alert
            if (data.has_open_ticket && data.open_ticket) {
              if (openTicketWarning) {
                openTicketWarning.classList.remove("d-none");
                openTicketWarning.innerHTML = `
                  <div class="alert alert-warning border-warning shadow-sm d-flex align-items-center justify-content-between mb-0">
                    <div>
                      <i class="bi bi-exclamation-triangle-fill fs-4 text-warning me-2"></i>
                      <strong>هشدار قبض باز:</strong> این خودرو در حال حاضر یک قبض باز با شماره <strong>#${escapeHtml(data.open_ticket.serial_number)}</strong> در کارخانه دارد (ورود ساعت ${escapeHtml(data.open_ticket.time)} - کالا: ${escapeHtml(data.open_ticket.product)}).
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
      }, 250);
    }

    // 1. Part 1 (2 digits) - Fast Keyboard Flow
    p1.addEventListener("input", function () {
      this.value = toEnDigits(this.value).replace(/[^0-9]/g, "");
      if (this.value.length >= 2) {
        pLetter.focus();
      }
      syncPlateString();
    });

    p1.addEventListener("keydown", function (e) {
      if (e.key === "Enter") {
        e.preventDefault();
        pLetter.focus();
        return;
      }
      // If already 2 digits and user presses another printable key:
      if (this.value.length >= 2 && !e.ctrlKey && !e.altKey && !e.metaKey && e.key.length === 1) {
        const key = e.key;
        // User typed a digit while p1 has 2 digits -> route immediately to p2
        if (/[0-9۰-۹٠-٩]/.test(key)) {
          e.preventDefault();
          p2.value = toEnDigits(key);
          p2.focus();
          p2.setSelectionRange(p2.value.length, p2.value.length);
          p2.dispatchEvent(new Event("input", { bubbles: true }));
          syncPlateString();
          return;
        }
        // User typed a Persian letter -> select letter in pLetter, then focus p2
        for (let opt of pLetter.options) {
          if (opt.value === key || opt.text === key || (key === "ا" && opt.value === "الف")) {
            e.preventDefault();
            pLetter.value = opt.value;
            pLetter.dispatchEvent(new Event("change", { bubbles: true }));
            p2.focus();
            if (p2.select) p2.select();
            syncPlateString();
            return;
          }
        }
      }
    });

    // 2. Letter Select - Fast Keyboard Flow
    pLetter.addEventListener("change", function () {
      p2.focus();
      if (p2.select) p2.select();
      syncPlateString();
    });

    pLetter.addEventListener("keydown", function (e) {
      if (e.ctrlKey || e.altKey || e.metaKey) return;

      // Enter, Space, Tab, ArrowLeft (moving forward in RTL) -> Move to p2
      if (e.key === "Enter" || e.key === " " || e.key === "ArrowLeft") {
        if (e.key !== "Tab") e.preventDefault();
        p2.focus();
        if (p2.select) p2.select();
        return;
      }

      // Backspace or ArrowRight (moving backward in RTL) -> Move back to p1
      if (e.key === "Backspace" || e.key === "ArrowRight") {
        e.preventDefault();
        p1.focus();
        if (p1.select) p1.select();
        return;
      }

      // If user types a DIGIT on the letter dropdown -> route immediately to p2!
      if (/[0-9۰-۹٠-٩]/.test(e.key)) {
        e.preventDefault();
        p2.value = toEnDigits(e.key);
        p2.focus();
        p2.setSelectionRange(p2.value.length, p2.value.length);
        p2.dispatchEvent(new Event("input", { bubbles: true }));
        syncPlateString();
        return;
      }

      // If user types a Persian letter -> select in dropdown and jump to p2!
      const k = e.key;
      for (let opt of pLetter.options) {
        if (opt.value === k || opt.text === k || (k === "ا" && opt.value === "الف")) {
          e.preventDefault();
          pLetter.value = opt.value;
          pLetter.dispatchEvent(new Event("change", { bubbles: true }));
          p2.focus();
          if (p2.select) p2.select();
          syncPlateString();
          return;
        }
      }
    });

    // 3. Part 2 (3 digits) - Fast Keyboard Flow
    p2.addEventListener("input", function () {
      this.value = toEnDigits(this.value).replace(/[^0-9]/g, "");
      if (this.value.length >= 3) {
        pIran.focus();
        if (pIran.select) pIran.select();
      }
      syncPlateString();
    });

    p2.addEventListener("keydown", function (e) {
      if (e.key === "Enter") {
        e.preventDefault();
        pIran.focus();
        if (pIran.select) pIran.select();
        return;
      }
      if (e.key === "Backspace" && !this.value) {
        e.preventDefault();
        pLetter.focus();
        return;
      }
      // If already 3 digits and user types another digit -> route to pIran
      if (this.value.length >= 3 && !e.ctrlKey && !e.altKey && !e.metaKey && /[0-9۰-۹٠-٩]/.test(e.key)) {
        e.preventDefault();
        pIran.value = toEnDigits(e.key);
        pIran.focus();
        pIran.setSelectionRange(pIran.value.length, pIran.value.length);
        pIran.dispatchEvent(new Event("input", { bubbles: true }));
        syncPlateString();
        return;
      }
    });

    // 4. Iran Code (2 digits) - Fast Keyboard Flow
    pIran.addEventListener("input", function () {
      this.value = toEnDigits(this.value).replace(/[^0-9]/g, "");
      syncPlateString();
    });

    pIran.addEventListener("keydown", function (e) {
      if (e.key === "Backspace" && !this.value) {
        e.preventDefault();
        p2.focus();
        if (p2.select) p2.select();
        return;
      }
      if (e.key === "Enter") {
        e.preventDefault();
        syncPlateString();
        // Advance to next input on form
        const form = this.form;
        if (form) {
          const focusables = Array.from(
            form.querySelectorAll("input:not([type=hidden]):not([disabled]), select:not([disabled]), textarea:not([disabled])")
          );
          const idx = focusables.indexOf(this);
          if (idx > -1 && idx + 1 < focusables.length) {
            focusables[idx + 1].focus();
            if (focusables[idx + 1].select) focusables[idx + 1].select();
          }
        }
        return;
      }
    });

    // Paste handling on plate inputs: paste full plate e.g. "56 د 789 - ایران 21"
    p1.addEventListener("paste", function (e) {
      const pasted = (e.clipboardData || window.clipboardData).getData("text");
      if (!pasted) return;
      const match = pasted.match(/(\d{2}|[۰-۹]{2})\s*([^\d\s\-_]+)\s*(\d{3}|[۰-۹]{3})\s*(?:-?\s*(?:ایران|ايران)?\s*(\d{2}|[۰-۹]{2}))?/);
      if (match) {
        e.preventDefault();
        p1.value = toEnDigits(match[1]);
        if (match[2]) {
          const lk = match[2];
          for (let opt of pLetter.options) {
            if (opt.value === lk || opt.text === lk || (lk === "ا" && opt.value === "الف")) {
              pLetter.value = opt.value;
              break;
            }
          }
        }
        if (match[3]) p2.value = toEnDigits(match[3]);
        if (match[4]) pIran.value = toEnDigits(match[4]);
        syncPlateString();
        pIran.focus();
      }
    });

    // Clear autofilled flag when operator manually edits fields
    ["id_driver_name_custom", "id_driver_mobile_custom"].forEach((id) => {
      const el = document.getElementById(id);
      if (el) {
        el.addEventListener("input", function () {
          delete this.dataset.autofilled;
        });
      }
    });
    const vTypeEl = document.getElementById("id_vehicle_type");
    if (vTypeEl) {
      vTypeEl.addEventListener("change", function (e) {
        if (e.isTrusted) delete this.dataset.autofilled;
      });
    }

    if (pDisplay) {
      pDisplay.addEventListener("input", function () {
        const val = this.value.trim();
        if (isTicketPage && val.length >= 4) {
          triggerPlateLookup(val);
        }
      });
      pDisplay.addEventListener("change", function () {
        const val = this.value.trim();
        if (isTicketPage && val.length >= 4) {
          triggerPlateLookup(val);
        }
      });
    }

    // Trigger on initial page load if values exist
    if (p1.value || p2.value || pIran.value) {
      syncPlateString();
    }
  }

  // 6. Real-Time High-Precision Weighbridge Calculations
  function initLiveWeightCalculations() {
    const w1Input = document.getElementById("id_first_weight");
    const w2Input = document.getElementById("id_second_weight");
    const sentInput = document.getElementById("id_sent_weight");
    const lossPctInput = document.getElementById("id_loss_percent");
    const lossWeightInput = document.getElementById("id_loss_weight");
    const isLossOverridden = document.getElementById("id_is_loss_overridden");
    const isEditPage = !!document.getElementById("ticket-edit-form") || !!document.querySelector(".ticket-edit-form");

    if (isEditPage && lossWeightInput) {
      lossWeightInput.readOnly = false;
      lossWeightInput.removeAttribute("readonly");
    }

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

    function calculateAll(sourceEl) {
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
      const isOverridden = isLossOverridden && isLossOverridden.checked;
      const isTypingLossWeight = (document.activeElement === lossWeightInput) || (sourceEl === lossWeightInput);

      if (isTypingLossWeight) {
        lossKg = parseNum(lossWeightInput ? lossWeightInput.value : 0);
      } else if (isOverridden && lossWeightInput && lossWeightInput.value.trim() !== "") {
        lossKg = parseNum(lossWeightInput.value);
      } else if (lossWeightInput && lossWeightInput.value.trim() !== "" && parseNum(lossWeightInput.value) > 0 && lossPct === 0) {
        lossKg = parseNum(lossWeightInput.value);
        if (isLossOverridden && !isLossOverridden.checked) {
          isLossOverridden.checked = true;
        }
      } else {
        if (net > 0 && lossPct > 0) {
          lossKg = (net * lossPct) / 100;
        }
        if (lossWeightInput && !isOverridden && !isTypingLossWeight) {
          lossWeightInput.value = lossKg > 0 ? Math.round(lossKg * 100) / 100 : "";
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

    if (lossWeightInput) {
      lossWeightInput.addEventListener("input", function () {
        const val = parseNum(this.value);
        if (this.value.trim() !== "" && val > 0) {
          if (isLossOverridden && !isLossOverridden.checked) {
            isLossOverridden.checked = true;
          }
        }
        calculateAll(this);
      });
      lossWeightInput.addEventListener("change", function () {
        calculateAll(this);
      });
    }

    [w1Input, w2Input, sentInput, lossPctInput].forEach((el) => {
      if (el) {
        el.addEventListener("input", () => calculateAll(el));
        el.addEventListener("change", () => calculateAll(el));
      }
    });

    if (isLossOverridden) {
      isLossOverridden.addEventListener("change", function () {
        if (lossWeightInput) {
          if (!isEditPage) {
            lossWeightInput.readOnly = !this.checked;
          }
          if (this.checked) lossWeightInput.focus();
        }
        calculateAll(this);
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

  // 7. Auto-Clear Default & Zero Numbers on Weight Inputs Click/Focus
  function initAutoClearWeightInputs() {
    const weightSelector = [
      "#id_first_weight",
      "#id_second_weight",
      "#id_sent_weight",
      "#id_loss_percent",
      "#id_loss_weight",
      "#id_empty_weight",
      "#id_standard_tare_weight",
      "#id_standard_tolerance_kg",
      "#id_default_loss_percent",
      ".weight-hero-box input",
      ".weight-input",
      "input.weight-auto-clear",
      "input[name='first_weight']",
      "input[name='second_weight']",
      "input[name='sent_weight']",
      "input[name='loss_percent']",
      "input[name='loss_weight']",
      "input[name='empty_weight']"
    ].join(",");

    function isDefaultZero(val) {
      if (val === null || val === undefined) return false;
      const str = String(val).trim();
      if (!str) return false;
      const clean = str.replace(/,/g, "")
        .replace(/۰/g, "0").replace(/۱/g, "1").replace(/۲/g, "2")
        .replace(/۳/g, "3").replace(/۴/g, "4").replace(/۵/g, "5")
        .replace(/۶/g, "6").replace(/۷/g, "7").replace(/۸/g, "8").replace(/۹/g, "9");
      const num = parseFloat(clean);
      return !isNaN(num) && num === 0;
    }

    function processClearOrSelect(input) {
      if (!input || input.readOnly || input.disabled) return;
      if (isDefaultZero(input.value)) {
        input.value = "";
        input.dispatchEvent(new Event("input", { bubbles: true }));
      } else {
        try {
          input.select();
        } catch (e) {}
      }
    }

    // Auto clear zero on initial load for new forms
    document.querySelectorAll(weightSelector).forEach(function (el) {
      if (!el.readOnly && !el.disabled && isDefaultZero(el.value)) {
        if (!document.querySelector("input[name=ticket_id]") && (window.location.pathname.includes("/create/") || window.location.pathname.includes("/second-weight/"))) {
          el.value = "";
        }
      }
    });

    // Event delegation on focusin
    document.addEventListener("focusin", function (e) {
      const target = e.target;
      if (target && target.matches && target.matches(weightSelector)) {
        processClearOrSelect(target);
      }
    });

    // Event delegation on click
    document.addEventListener("click", function (e) {
      const target = e.target;
      if (target && target.matches && target.matches(weightSelector)) {
        if (isDefaultZero(target.value)) {
          processClearOrSelect(target);
        }
      }
    });

    // Auto clear zero on first keypress so numbers don't start with 0
    document.addEventListener("keydown", function (e) {
      const target = e.target;
      if (target && target.matches && target.matches(weightSelector)) {
        if (isDefaultZero(target.value) && e.key && e.key.length === 1 && !e.ctrlKey && !e.altKey && !e.metaKey) {
          target.value = "";
        }
      }
    });
  }

  // 10. Persian Number to Words Converter
  function numberToPersianWords(num) {
    if (num === null || num === undefined) return "";
    let str = toEnDigits(String(num)).replace(/\D/g, "");
    if (!str) return "";
    str = str.replace(/^0+/, "");
    if (str === "") return "صفر";

    const units = ["", "یک", "دو", "سه", "چهار", "پنج", "شش", "هفت", "هشت", "نه"];
    const teens = [
      "ده", "یازده", "دوازده", "سیزده", "چهارده",
      "پانزده", "شانزده", "هفده", "هجده", "نوزده"
    ];
    const tens = [
      "", "", "بیست", "سی", "چهل", "پنجاه",
      "شصت", "هفتاد", "هشتاد", "نود"
    ];
    const hundreds = [
      "", "یکصد", "دویست", "سیصد", "چهارصد",
      "پانصد", "ششصد", "هفتصد", "هشتصد", "نهصد"
    ];
    const scales = ["", "هزار", "میلیون", "میلیارد", "تریلیون", "کوآدریلیون"];

    function convertGroup(n) {
      const parts = [];
      const h = Math.floor(n / 100);
      const rem = n % 100;
      if (h > 0) parts.push(hundreds[h]);
      if (rem >= 10 && rem <= 19) {
        parts.push(teens[rem - 10]);
      } else {
        const t = Math.floor(rem / 10);
        const u = rem % 10;
        if (t > 0) parts.push(tens[t]);
        if (u > 0) parts.push(units[u]);
      }
      return parts.join(" و ");
    }

    const groups = [];
    while (str.length > 0) {
      groups.push(str.slice(-3));
      str = str.slice(0, -3);
    }

    const parts = [];
    for (let i = 0; i < groups.length; i++) {
      const val = parseInt(groups[i], 10);
      if (val > 0) {
        let groupWord = convertGroup(val);
        if (i > 0 && scales[i]) {
          groupWord += " " + scales[i];
        }
        parts.push(groupWord);
      }
    }

    return parts.reverse().join(" و ");
  }
  window.numberToPersianWords = numberToPersianWords;

  // 11. Amount Input 3-digit Separation & Real-time Words Underneath
  function initAmountWordsFormatters() {
    const amountInputs = document.querySelectorAll(
      "#id_freight_amount, input[name='freight_amount'], .format-amount-words"
    );

    amountInputs.forEach((input) => {
      if (input.dataset.amountFormatterInitialized === "true") return;
      input.dataset.amountFormatterInitialized = "true";

      const targetSelector = input.dataset.wordsContainer || "#freight-amount-words";
      let wordsContainer = document.querySelector(targetSelector);
      if (!wordsContainer) {
        const parent = input.closest(".col-md-6, .col-md-4, .col-md-3, .col-xl, .col-12");
        if (parent) {
          wordsContainer = parent.querySelector("#freight-amount-words, .amount-words-display");
        }
      }

      function updateFormattingAndWords() {
        const oldVal = input.value;
        const cursorPos = input.selectionStart || 0;

        const enOld = toEnDigits(oldVal);
        let digitsBeforeCursor = 0;
        for (let i = 0; i < cursorPos; i++) {
          if (/\d/.test(enOld[i])) {
            digitsBeforeCursor++;
          }
        }

        const cleanDigits = enOld.replace(/\D/g, "").replace(/^0+(?=\d)/, "");

        if (!cleanDigits) {
          input.value = "";
          if (wordsContainer) {
            wordsContainer.classList.add("d-none");
            const textSpan = wordsContainer.querySelector(".words-text");
            if (textSpan) textSpan.textContent = "";
          }
          return;
        }

        const formatted = cleanDigits.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
        input.value = formatted;

        // Restore cursor position seamlessly
        let newCursorPos = 0;
        let countedDigits = 0;
        for (let i = 0; i < formatted.length; i++) {
          if (/\d/.test(formatted[i])) {
            countedDigits++;
          }
          if (countedDigits >= digitsBeforeCursor) {
            newCursorPos = i + 1;
            break;
          }
        }
        if (digitsBeforeCursor === 0) newCursorPos = 0;
        if (newCursorPos > formatted.length) newCursorPos = formatted.length;

        try {
          input.setSelectionRange(newCursorPos, newCursorPos);
        } catch (err) {}

        // Update live words display
        if (wordsContainer) {
          const words = numberToPersianWords(cleanDigits);
          const textSpan = wordsContainer.querySelector(".words-text");
          if (words) {
            if (textSpan) {
              textSpan.textContent = words + " ریال";
            } else {
              wordsContainer.textContent = words + " ریال";
            }
            wordsContainer.classList.remove("d-none");
          } else {
            wordsContainer.classList.add("d-none");
            if (textSpan) textSpan.textContent = "";
          }
        }
      }

      input.addEventListener("input", updateFormattingAndWords);
      input.addEventListener("keyup", updateFormattingAndWords);
      input.addEventListener("change", updateFormattingAndWords);
      input.addEventListener("focus", updateFormattingAndWords);
      input.addEventListener("paste", function () {
        setTimeout(updateFormattingAndWords, 20);
      });

      // Handle Backspace when immediately following a comma
      input.addEventListener("keydown", function (e) {
        if (e.key === "Backspace" && this.selectionStart === this.selectionEnd && this.selectionStart > 1) {
          if (this.value[this.selectionStart - 1] === ",") {
            const pos = this.selectionStart;
            this.value = this.value.slice(0, pos - 2) + this.value.slice(pos - 1);
            this.setSelectionRange(pos - 2, pos - 2);
            e.preventDefault();
            this.dispatchEvent(new Event("input"));
          }
        }
      });

      // Initial execution for pre-populated values
      if (input.value && input.value.trim() !== "") {
        updateFormattingAndWords();
      }
      window.addEventListener("load", function () {
        if (input.value && input.value.trim() !== "") {
          updateFormattingAndWords();
        }
      });
    });
  }
  window.initAmountWordsFormatters = initAmountWordsFormatters;

  // DOM Ready Initializations
  document.addEventListener("DOMContentLoaded", function () {
    initKeyboardUX();
    initDisableWheelOnInputs();
    initDoubleSubmitPrevention();
    initPlateWidget();
    initLiveWeightCalculations();
    initAutoClearWeightInputs();
    initLiveClock();
    initSidebarActiveNav();
    initAmountWordsFormatters();

    // Restore density preference
    const savedDensity = localStorage.getItem("bascol_table_density");
    if (savedDensity) setTableDensity(savedDensity);
  });
})();
