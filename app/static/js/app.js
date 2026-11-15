/* TerraPulse AI — progressive enhancement */
(function () {
  "use strict";

  // ---- Service worker (offline shell) ----
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", function () {
      navigator.serviceWorker.register("/service-worker.js").catch(function () {
        /* offline shell is optional */
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
        if (!response.ok) throw new Error("feedback");
        return response.json();
      }).then(function () {
        var thanks = feedbackForm.getAttribute("data-thanks") || "";
        if (status) {
          status.classList.add("is-ok");
          status.textContent = thanks;
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
