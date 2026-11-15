/* TerraPulse AI — progressive enhancement */
(function () {
  "use strict";

  // ---- Service worker (offline shell) ----
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", function () {
      navigator.serviceWorker.register("/service-worker.js").catch(function (error) {
        console.error("Unable to register the service worker.", error);
      });
    });
  }

  // ---- Color theme ----
  var themeButton = document.querySelector("[data-theme-toggle]");
  var themeColor = document.querySelector('meta[name="theme-color"]');

  function applyTheme(theme) {
    var isDark = theme === "dark";
    document.documentElement.dataset.theme = isDark ? "dark" : "light";
    if (!themeButton) return;

    themeButton.setAttribute("aria-pressed", String(isDark));
    themeButton.title = isDark
      ? themeButton.getAttribute("data-label-dark")
      : themeButton.getAttribute("data-label-light");
    if (themeColor) themeColor.content = isDark ? "#201A12" : "#FAF7F1";
  }

  if (themeButton) {
    applyTheme(document.documentElement.dataset.theme === "dark" ? "dark" : "light");
    themeButton.addEventListener("click", function () {
      var nextTheme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
      applyTheme(nextTheme);
      try {
        window.localStorage.setItem("terrapulse-theme", nextTheme);
      } catch (error) {
        console.error("Unable to save the theme preference.", error);
      }
    });
  }

  // ---- Toast ----
  var toast = document.getElementById("toast");
  var toastTimer = null;

  function showToast(message) {
    if (!toast) return;
    toast.textContent = message;
    toast.classList.add("is-visible");
    if (toastTimer) window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(function () {
      toast.classList.remove("is-visible");
    }, 3800);
  }

  // ---- Read aloud ----
  var listenButton = document.querySelector("[data-listen]");
  var speechCard = document.querySelector("[data-speech]");
  var canSpeak = "speechSynthesis" in window && "SpeechSynthesisUtterance" in window;

  var voiceLang = {
    pt: "pt-PT",
    en: "en-US",
    chitewe: "pt-PT",
    sena: "pt-PT"
  };

  function translatedMessage(name, fallback) {
    return (document.body && document.body.getAttribute("data-i18n-" + name)) || fallback;
  }

  function pickVoice(lang) {
    var voices = window.speechSynthesis.getVoices();
    var prefix = (lang || "pt").toLowerCase().split("-")[0];
    for (var i = 0; i < voices.length; i += 1) {
      if (voices[i].lang && voices[i].lang.toLowerCase().indexOf(prefix) === 0) {
        return voices[i];
      }
    }
    return null;
  }

  function speak(text, lang) {
    if (!canSpeak) {
      showToast(
        translatedMessage(
          "speech-unsupported",
          "O seu telemóvel não suporta leitura em voz alta."
        )
      );
      return;
    }
    if (window.speechSynthesis.speaking) {
      window.speechSynthesis.cancel();
      return;
    }
    var utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = voiceLang[lang] || "pt-PT";
    utterance.rate = 0.94;
    utterance.pitch = 1;
    var voice = pickVoice(utterance.lang);
    if (voice) utterance.voice = voice;
    window.speechSynthesis.speak(utterance);
    if (lang !== "pt" && lang !== "en") {
      showToast(
        translatedMessage(
          "local-voice",
          "Voz local ainda não disponível; a ler com a voz padrão."
        )
      );
    }
  }

  if (listenButton && speechCard) {
    listenButton.addEventListener("click", function () {
      var text = speechCard.getAttribute("data-speech") || speechCard.textContent || "";
      var lang = document.documentElement.lang || "pt";
      speak(text.trim(), lang);
      listenButton.classList.add("is-speaking");
      window.setTimeout(function () {
        listenButton.classList.remove("is-speaking");
      }, 900);
    });
  }

  // ---- Decision selectors ----
  var autoSelects = document.querySelectorAll("[data-auto-submit]");
  for (var i = 0; i < autoSelects.length; i += 1) {
    autoSelects[i].addEventListener("change", function () {
      if (this.form) this.form.submit();
    });
  }

  var contextLink = document.querySelector("[data-open-context]");
  var contextDetails = document.getElementById("change-context");
  if (contextLink && contextDetails) {
    contextLink.addEventListener("click", function () {
      contextDetails.open = true;
      var select = contextDetails.querySelector("select");
      if (select) {
        window.setTimeout(function () {
          select.focus();
        }, 60);
      }
    });
  }
  if (contextDetails && window.location.hash === "#change-context") {
    contextDetails.open = true;
  }

  // ---- Field outcome follow-up ----
  var followupForm = document.querySelector("[data-feedback-outcome]");
  var followupStorageKey = "terrapulse-feedback-followups-v1";

  function readFollowups() {
    try {
      var raw = window.localStorage.getItem(followupStorageKey);
      var records = raw ? JSON.parse(raw) : [];
      if (!Array.isArray(records)) throw new Error("Stored follow-ups are invalid.");
      return records.filter(function (record) {
        return record && typeof record.submission_id === "string" &&
          typeof record.followup_due_at === "string";
      });
    } catch (error) {
      console.error("Unable to read saved feedback follow-ups.", error);
      return null;
    }
  }

  function writeFollowups(records) {
    try {
      window.localStorage.setItem(followupStorageKey, JSON.stringify(records));
      return true;
    } catch (error) {
      console.error("Unable to save feedback follow-up.", error);
      return false;
    }
  }

  function saveFollowup(record) {
    var records = readFollowups();
    if (!records) return false;
    records = records.filter(function (saved) {
      return saved.submission_id !== record.submission_id;
    });
    records.push(record);
    return writeFollowups(records);
  }

  function removeFollowup(submissionId) {
    var records = readFollowups();
    if (!records) return false;
    return writeFollowups(records.filter(function (record) {
      return record.submission_id !== submissionId;
    }));
  }

  function showDueFollowup() {
    if (!followupForm) return;
    var records = readFollowups();
    if (!records) return;
    var dueRecord = records.find(function (record) {
      return Date.parse(record.followup_due_at) <= Date.now();
    });
    if (!dueRecord) {
      followupForm.hidden = true;
      return;
    }

    followupForm.querySelector("[name='submission_id']").value =
      dueRecord.submission_id;
    var dateInput = followupForm.querySelector("[name='planting_date']");
    dateInput.min = dueRecord.decision_date || "";
    followupForm.hidden = false;
  }

  showDueFollowup();

  if (followupForm && window.fetch) {
    followupForm.addEventListener("submit", function (event) {
      event.preventDefault();
      var button = followupForm.querySelector("button[type='submit']");
      var status = followupForm.querySelector("[data-feedback-outcome-status]");
      var data = new FormData(followupForm);
      var payload = {};
      data.forEach(function (value, key) {
        payload[key] = value;
      });
      var sending = followupForm.getAttribute("data-sending") || "";
      if (status) {
        status.classList.remove("is-ok", "is-error");
        status.textContent = sending;
      }
      if (button) button.disabled = true;

      fetch(followupForm.action, {
        method: "POST",
        headers: {
          "Accept": "application/json",
          "Content-Type": "application/json"
        },
        body: JSON.stringify(payload),
        credentials: "same-origin"
      }).then(function (response) {
        return response.json().then(function (result) {
          return { response: response, result: result };
        });
      }).then(function (reply) {
        var response = reply.response;
        var result = reply.result;
        if (response.ok) {
          removeFollowup(payload.submission_id);
          if (status) {
            status.classList.add("is-ok");
            status.textContent = followupForm.getAttribute("data-thanks") || "";
          }
          showToast(followupForm.getAttribute("data-thanks") || "");
          showDueFollowup();
          return;
        }

        if (result.error && result.error.code === "field_outcome_not_due") {
          if (status) status.textContent = followupForm.getAttribute("data-not-due") || "";
        } else if (result.error && result.error.code === "field_outcome_already_reported") {
          removeFollowup(payload.submission_id);
          if (status) {
            status.classList.add("is-ok");
            status.textContent =
              followupForm.getAttribute("data-already-reported") || "";
          }
          showDueFollowup();
        } else {
          throw new Error("field outcome");
        }
      }).catch(function () {
        if (status) {
          status.classList.add("is-error");
          status.textContent = followupForm.getAttribute("data-error") || "";
        }
      }).then(function () {
        if (button && !followupForm.hidden) button.disabled = false;
      });
    });
  }

  // ---- One-tap feedback ----
  var feedbackForm = document.querySelector("[data-feedback]");
  if (feedbackForm && window.fetch) {
    feedbackForm.addEventListener("submit", function (event) {
      event.preventDefault();
      var button = event.submitter || document.activeElement;
      var status = feedbackForm.querySelector("[data-feedback-status]");
      var buttons = feedbackForm.querySelectorAll("button[name='choice']");
      var payload = {};
      var data = new FormData(feedbackForm);
      data.forEach(function (value, key) {
        payload[key] = value;
      });
      if (button && button.name === "choice") {
        payload.choice = button.value;
      }
      if (!payload.choice) return;

      for (var j = 0; j < buttons.length; j += 1) {
        buttons[j].disabled = true;
      }
      if (status) {
        status.classList.remove("is-ok", "is-error");
        status.textContent = feedbackForm.getAttribute("data-sending") || "";
      }

      fetch(feedbackForm.action, {
        method: "POST",
        headers: {
          "Accept": "application/json",
          "Content-Type": "application/json"
        },
        body: JSON.stringify(payload),
        credentials: "same-origin"
      }).then(function (response) {
        return response.json().then(function (result) {
          if (!response.ok) throw new Error("feedback");
          return result;
        });
      }).then(function (result) {
        var thanks = feedbackForm.getAttribute("data-thanks") || "";
        var followupSaved = true;
        if (payload.choice === "planted" && result.followup_due_at) {
          followupSaved = saveFollowup({
            submission_id: payload.submission_id,
            followup_due_at: result.followup_due_at,
            decision_date: payload.reference_date
          });
        }
        if (status) {
          status.classList.add(followupSaved ? "is-ok" : "is-error");
          status.textContent = followupSaved
            ? thanks
            : feedbackForm.getAttribute("data-followup-storage-error") || thanks;
        }
        if (button && button.name === "choice") {
          button.setAttribute("aria-pressed", "true");
        }
        showToast(thanks);
      }).catch(function () {
        if (status) {
          status.classList.add("is-error");
          status.textContent = feedbackForm.getAttribute("data-error") || "";
        }
        for (var k = 0; k < buttons.length; k += 1) {
          buttons[k].disabled = false;
        }
      });
    });
  }
})();
