/**
 * Fast Operator Experience & Realtime Calculations for Prima Bascol Weighbridge
 */

document.addEventListener("DOMContentLoaded", function () {
  initKeyboardNavigation();
  initPlateSync();
  initLiveCalculations();
  initPersianDigits();
  initAutoRefreshTime();
});

// 1. Enter Key Workflow: advances to next field seamlessly
function initKeyboardNavigation() {
  const form = document.getElementById("weighbridge-ticket-form");
  if (!form) return;

  const inputs = Array.from(
    form.querySelectorAll("input:not([type=hidden]):not([disabled]), select:not([disabled]), textarea:not([disabled])")
  );

  inputs.forEach((input, index) => {
    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && e.target.tagName !== "TEXTAREA" && !e.target.classList.contains("btn-submit")) {
        e.preventDefault();
        const nextInput = inputs[index + 1];
        if (nextInput) {
          nextInput.focus();
          if (nextInput.select) nextInput.select();
        }
      }
    });
  });
}

// 2. Iranian License Plate UI Sync
function initPlateSync() {
  const p1 = document.getElementById("plate_part1");
  const pLetter = document.getElementById("plate_letter");
  const p2 = document.getElementById("plate_part2");
  const pIran = document.getElementById("plate_iran");
  const pDisplay = document.getElementById("license_plate_display");

  if (!p1 || !pLetter || !p2 || !pIran || !pDisplay) return;

  function updatePlate() {
    const v1 = p1.value.trim();
    const vL = pLetter.value.trim();
    const v2 = p2.value.trim();
    const vI = pIran.value.trim();

    if (v1 && vL && v2 && vI) {
      pDisplay.value = `${v1} ${vL} ${v2} - ایران ${vI}`;
    } else if (!pDisplay.value) {
      pDisplay.value = "";
    }
  }

  [p1, p2, pIran].forEach((el) => {
    el.addEventListener("input", function () {
      this.value = this.value.replace(/[^0-9۰-۹]/g, "");
      updatePlate();
    });
  });

  pLetter.addEventListener("change", updatePlate);

  // Auto focus jump in plate parts
  p1.addEventListener("input", function () {
    if (this.value.length >= 2) pLetter.focus();
  });
  p2.addEventListener("input", function () {
    if (this.value.length >= 3) pIran.focus();
  });
}

// 3. Live Weight Calculation with thousand separators
function initLiveCalculations() {
  const w1Input = document.getElementById("id_first_weight");
  const w2Input = document.getElementById("id_second_weight");
  const sentInput = document.getElementById("id_sent_weight");
  const lossPctInput = document.getElementById("id_loss_percent");
  const lossWeightInput = document.getElementById("id_loss_weight");
  const isLossOverridden = document.getElementById("id_is_loss_overridden");

  // Output cards
  const grossCard = document.getElementById("preview-gross");
  const tareCard = document.getElementById("preview-tare");
  const netCard = document.getElementById("preview-net");
  const lossCard = document.getElementById("preview-loss");
  const finalCard = document.getElementById("preview-final");
  const diffCard = document.getElementById("preview-diff");
  const warningBox = document.getElementById("tolerance-warning");

  function cleanNum(val) {
    if (!val) return 0;
    const str = String(val).replace(/,/g, "").trim();
    const num = parseFloat(str);
    return isNaN(num) ? 0 : num;
  }

  function formatThousand(num) {
    if (num === null || num === undefined || isNaN(num)) return "0";
    const rounded = Math.round(num * 100) / 100;
    return rounded.toLocaleString("fa-IR", {
      minimumFractionDigits: 0,
      maximumFractionDigits: 2
    });
  }

  function calculate() {
    const w1 = cleanNum(w1Input ? w1Input.value : 0);
    const w2 = w2Input ? cleanNum(w2Input.value) : null;
    const hasW2 = w2Input && w2Input.value.trim() !== "";
    const sent = cleanNum(sentInput ? sentInput.value : 0);
    const lossPct = cleanNum(lossPctInput ? lossPctInput.value : 0);

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
    const isTypingLossWeight = (document.activeElement === lossWeightInput);

    if (isTypingLossWeight) {
      lossKg = cleanNum(lossWeightInput.value);
    } else if (isOverridden && lossWeightInput && lossWeightInput.value.trim() !== "") {
      lossKg = cleanNum(lossWeightInput.value);
    } else if (lossWeightInput && lossWeightInput.value.trim() !== "" && cleanNum(lossWeightInput.value) > 0 && lossPct === 0) {
      lossKg = cleanNum(lossWeightInput.value);
      if (isLossOverridden && !isLossOverridden.checked) {
        isLossOverridden.checked = true;
      }
    } else {
      if (net > 0 && lossPct > 0) {
        lossKg = (net * lossPct) / 100;
      }
      if (lossWeightInput && !isOverridden && !isTypingLossWeight) {
        lossWeightInput.value = lossKg > 0 ? (Math.round(lossKg * 100) / 100) : "";
      }
    }

    const final = Math.max(0, net - lossKg);
    const diff = sent > 0 && net > 0 ? net - sent : 0;
    const diffPct = sent > 0 ? ((diff / sent) * 100).toFixed(2) : 0;

    // Update DOM elements if present
    if (grossCard) grossCard.textContent = formatThousand(gross);
    if (tareCard) tareCard.textContent = formatThousand(tare);
    if (netCard) netCard.textContent = formatThousand(net);
    if (lossCard) lossCard.textContent = formatThousand(lossKg);
    if (finalCard) finalCard.textContent = formatThousand(final);
    if (diffCard) {
      diffCard.textContent = (diff > 0 ? "+" : "") + formatThousand(diff);
    }

    // Tolerance check warning
    if (warningBox) {
      const maxToleranceKg = parseFloat(warningBox.dataset.toleranceKg || 50);
      if (sent > 0 && net > 0 && Math.abs(diff) > maxToleranceKg) {
        warningBox.classList.remove("d-none");
        warningBox.innerHTML = `<i class="bi bi-exclamation-triangle-fill me-1"></i> هشدار مغایرت: اختلاف وزن با بارنامه (${formatThousand(Math.abs(diff))} کیلوگرم) بیش از سقف مجاز (${maxToleranceKg} کیلوگرم) است!`;
      } else {
        warningBox.classList.add("d-none");
      }
    }
  }

  // Bind event listeners
  if (lossWeightInput) {
    lossWeightInput.addEventListener("input", function () {
      const val = cleanNum(this.value);
      if (this.value.trim() !== "" && val > 0) {
        if (isLossOverridden && !isLossOverridden.checked) {
          isLossOverridden.checked = true;
        }
      }
      calculate();
    });
    lossWeightInput.addEventListener("change", calculate);
  }

  [w1Input, w2Input, sentInput, lossPctInput].forEach((el) => {
    if (el) {
      el.addEventListener("input", calculate);
      el.addEventListener("change", calculate);
    }
  });

  if (isLossOverridden) {
    isLossOverridden.addEventListener("change", function () {
      const reasonBox = document.getElementById("loss-override-reason-group");
      if (reasonBox) {
        if (this.checked) {
          reasonBox.classList.remove("d-none");
          if (lossWeightInput) lossWeightInput.removeAttribute("readonly");
        } else {
          reasonBox.classList.add("d-none");
          if (lossWeightInput) lossWeightInput.setAttribute("readonly", "readonly");
          calculate();
        }
      }
    });
  }

  // Run calculation initially
  calculate();
}

// 4. Convert all inputs to Persian digits on display or format
function initPersianDigits() {
  // Add clock update
  const clockEl = document.getElementById("live-clock");
  if (clockEl) {
    setInterval(() => {
      const now = new Date();
      const h = String(now.getHours()).padStart(2, "0");
      const m = String(now.getMinutes()).padStart(2, "0");
      const s = String(now.getSeconds()).padStart(2, "0");
      clockEl.textContent = `${h}:${m}:${s}`;
    }, 1000);
  }
}

function initAutoRefreshTime() {
  // Automatically fill current time in time fields if empty
  const timeFields = document.querySelectorAll(".auto-current-time");
  timeFields.forEach((f) => {
    if (!f.value) {
      const now = new Date();
      const h = String(now.getHours()).padStart(2, "0");
      const m = String(now.getMinutes()).padStart(2, "0");
      f.value = `${h}:${m}`;
    }
  });
}
