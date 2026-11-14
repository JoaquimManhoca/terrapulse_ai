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

  // ---- Interactive daily forecast ----
  var weatherDays = document.querySelectorAll("[data-weather-day]");
  var weatherScene = document.querySelector("[data-weather-scene]");
  var weatherLabel = document.querySelector("[data-weather-label]");
  var weatherCaption = document.querySelector("[data-weather-caption]");
  var weatherProbability = document.querySelector("[data-weather-probability]");

  for (var dayIndex = 0; dayIndex < weatherDays.length; dayIndex += 1) {
    weatherDays[dayIndex].addEventListener("click", function () {
      var condition = this.getAttribute("data-condition");
      var label = this.getAttribute("data-label");
      var caption = this.getAttribute("data-caption");
      var probability = this.getAttribute("data-probability");
      var selectedIcon = this.querySelector(".weather-day-icon .icon");

      for (var selectedIndex = 0; selectedIndex < weatherDays.length; selectedIndex += 1) {
        var isSelected = weatherDays[selectedIndex] === this;
        weatherDays[selectedIndex].setAttribute("aria-pressed", String(isSelected));
        weatherDays[selectedIndex].classList.toggle("is-active", isSelected);
      }

      if (weatherScene && selectedIcon) {
        var icon = selectedIcon.cloneNode(true);
        icon.setAttribute("width", "64");
        icon.setAttribute("height", "64");
        while (weatherScene.firstChild) {
          weatherScene.removeChild(weatherScene.firstChild);
        }
        weatherScene.appendChild(icon);
        weatherScene.className = "weather-art weather-art--" + condition;
        var probabilityText = probability && weatherProbability
          ? ", " + probability + "% " + weatherProbability.getAttribute("data-label")
          : "";
        weatherScene.setAttribute("aria-label", label + ", " + caption + probabilityText);
      }
      if (weatherLabel) weatherLabel.textContent = label;
      if (weatherCaption) weatherCaption.textContent = caption;
      if (weatherProbability) {
        weatherProbability.hidden = !probability;
        weatherProbability.textContent = probability
          ? probability + "% " + weatherProbability.getAttribute("data-label")
          : "";
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
    chitewe: "pt-PT",
    sena: "pt-PT"
  };

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
      showToast("O seu telemóvel não suporta leitura em voz alta.");
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
    if (lang !== "pt") {
      showToast("Voz local ainda não disponível; a ler em português.");
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
})();
