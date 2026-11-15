# TerraPulse AI — NASA Space Apps Challenge submission kit

## One-line pitch

TerraPulse AI tells smallholder farmers in Manica, Mozambique whether to plant
maize now or wait, using NASA GPM IMERG rainfall, a validated onset model and a
30-day action plan.

## 30-second demo script

Manica farmers often lose seed when the first rain stops for a week. TerraPulse
AI answers one question: plant now or wait? It combines NASA IMERG rainfall,
historical false-onset risk and a 16-day Open-Meteo forecast. The decision page
shows a clear recommendation, a 30-day plan and the source and confidence behind
it. The first 16 days use the forecast; the remaining 14 use IMERG climatology,
clearly labelled. It works offline as a PWA and speaks Portuguese, English,
Chitewe and Sena.

## 7-slide outline

1. **Problem** — Farmers plant on the first rain; a dry spell destroys the seed.
2. **Person** — A maize farmer in Manica needs a decision today, not a dashboard.
3. **Insight** — The risk is not only how much rain falls, but whether the onset
   will hold for the next 21 days.
4. **Solution** — One recommendation: plant now, wait, plant in N days or high
   risk, with reasons and a 30-day action plan.
5. **NASA data and method** — IMERG Final/Early, onset and false-onset rules,
   Random Forest, Open-Meteo for the short-term forecast.
6. **Demo** — Decision page, 30-day plan, confidence/source card, offline mode,
   local languages.
7. **Impact and next steps** — Protect seed and income; pilot with farmers and
   rain gauges; expand to other districts and crops.

## AI usage declaration

TerraPulse AI uses AI-assisted software development for code review, tests and
documentation. The rainfall model is a Random Forest trained on NASA IMERG data;
it is not a generative AI model. No AI-generated images, video or audio are used
in the submission. If the team adds generated media later, it must be watermarked
and disclosed. NASA does not endorse this project.

## Data attribution

- NASA GPM IMERG Final Daily (`GPM_3IMERGDF`) and Early Daily (`GPM_3IMERGDE`),
  0.1° resolution. Rainfall is the mean of valid cells over the Manica bounding
  box: `32.69834, -19.13725, 33.17879, -18.70926`.
- Open-Meteo for the 16-day precipitation forecast.
- NASA GPM / GES DISC precipitation data are courtesy of NASA. Open-Meteo is
  credited for the short-term forecast.

## How the 30-day plan works

- Days 1–16: Open-Meteo forecast, labelled **Forecast**.
- Days 17–30: historical probability for the same calendar date across the
  available IMERG years, labelled **Climatology**. This is not a forecast.
- Actions: **Plant**, **Prepare**, **Wait** and **Monitor**.
- If the latest observation is older than 7 days, the plan does not recommend
  planting.

## Judge criteria mapping

- **Impact** — Protects seed and income for smallholder maize farmers.
- **Creativity** — Turns satellite rainfall into one decision and a 30-day plan.
- **Validity** — Transparent rules, historical false-onset rate, model version,
  source and coverage shown in the app.
- **Relevance** — Directly addresses climate adaptation and food security in
  Manica.
- **Presentation** — Clear 30-second story, mobile-first UI, offline PWA and four
  languages.

## Links and run instructions

- App: <https://terrapulseai-two.vercel.app>
- Repository: <https://github.com/gruta-tech/nassa-app2>
- Local run:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe run.py
```

## Known limitations

- IMERG is an estimate, especially over complex terrain.
- The onset rule is not yet calibrated with local rain gauges.
- Chitewe and Sena translations are complete but still need native review.
- No field-level soil moisture or parcel boundary data yet.
