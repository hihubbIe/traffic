# Belval ⇄ Thionville Traffic — Investigation & Product Definition

_Status: investigation, 2026-11-04. Nothing is built yet._

> **Constraints (set 2026-11-04):** personal project, single user. **€0 budget**: free and open data only. **Runs locally on this PC**: no always-on server for now. A Raspberry Pi is available later as an *optional* collector. Where earlier sections mention paid APIs or a 24/7 collector, §11 replaces them.

_Every fact here is tagged:_
- **[V]**: verified against a source during this investigation (link given)
- **[K]**: well-established domain knowledge, not re-checked this time
- **[?]**: has to be confirmed by hand, or measured once data starts flowing

---

## 1. What the app has to answer

"See and predict traffic" turns into five concrete questions. If the app can't answer them better than Google Maps or Waze, there's no point building it:

| # | Question | Why Google/Waze can't answer it |
|---|---|---|
| Q1 | **When should I leave** (Belval→Thionville in the evening, Thionville→Belval in the morning) to minimise door-to-door time, and how sure is that? | They give one ETA for "now". They don't give a calibrated *distribution* across departure times. |
| Q2 | **Which corridor**: A31→A3→A13, A30→Audun-le-Tiche→Belval, or the local D-roads through Volmerange/Rumelange/Kayl? | They choose for you and don't explain why, or when the ranking flips. |
| Q3 | **Car, carpool, train or bus** today? Train capacity and reliability feed directly into road demand. | They treat modes separately. Nobody models how a TER cancellation pushes people back onto the A31. |
| Q4 | **What breaks the network, and where does the queue go?** Roadworks, an interchange closure, a rail strike, snow, a Rockhal concert, a French public holiday that isn't a Luxembourgish one. | Waze reacts after the fact. It has no what-if mode. |
| Q5 | **Structural view.** Which choke points rule the corridor, how much capacity they have against demand, and what changes with the A3 at 2×3, A31bis, Bettembourg rail and the Micheville link. | Nobody publishes this. |

So the app is three tools in one: **a nowcast/forecast tool** (Q1–Q3), **a scenario simulator** (Q4) and **a network observatory** (Q5). They share one network model.

> On wording: *frontalier* is the right French word. In English: **cross-border commuter** (or "cross-border worker").

---

## 2. Study area: why it's bigger than "the road"

Belval (Esch-sur-Alzette/Sanem) and Thionville are about 25 km apart, but traffic between them depends on a much larger system.

### 2.1 Core corridors (at least 4 competing paths)

| ID | Path | Notes |
|---|---|---|
| **C1 Motorway** | Thionville (A31: Beauregard/Linkling/Terville/Metzange junctions) → A31 north, **2×2 lanes** → border at Zoufftgen/Frisange → **A3** → **Croix de Bettembourg** → **A13 west (Collectrice du Sud)** → Lankelz → **A4** / Raemerich → Belval-Université / Belval-Gare | Main route. A31 Thionville–border is 2×2 (widening to 2×3 is part of the A31bis plan [V](https://www.linfodurable.fr/metz-luxembourg-coup-daccelerateur-sur-un-projet-dautoroute-bis-54538)). |
| **C2 West** | Thionville → **A30** (Florange/Hayange/Fontoy) → D-roads via Aumetz/Audun-le-Tiche → Micheville → **Micheville link → A4** → Belval | Micheville link built to take load off Audun-le-Tiche and Esch [V](https://travaux.public.lu/dam-assets/fr/publications/m/mise-en-service-liaison-micheville-1/LP_Plaquette-MICHEVILLE_A3-opt.pdf). About **25,000 vehicles/day** cross Audun-le-Tiche (local official, date unknown) [V](https://paperjam.lu/article/mobilisation-cote-francais-con). |
| **C3 Middle/local** | Thionville → Hettange-Grande / Volmerange-les-Mines → Dudelange → Kayl/Tétange → Esch | Rat-run when C1 is jammed at the border. Moselle plans to widen 3 RDs towards Luxembourg [V](https://www.lesfrontaliers.lu/?p=1161694); which ones exactly is [?]. |
| **C4 Ottange/Rumelange** | Thionville/Hayange → Ottange → Rumelange → Esch | Same role as C3 [?]. |

### 2.2 The "upstream" effect you described

C1 shares its key choke points with the much larger flow **towards Luxembourg City**:
- At the Croix de Bettembourg, A31 traffic splits between **A3 → Gasperich/Cloche d'Or/Kirchberg** and **A13 → Esch/Belval**.
- When A3 towards the city is jammed, the queue backs up through Bettembourg and Livange to the border, and Belval-bound drivers sit in a queue they have nothing to do with.
- When A3 runs **smoothly** (holidays, 2×3 sections opening, good rail days), the bottleneck **moves**: more vehicles get through the border section per hour, and the next constraint becomes the merge and weave sections or the A13/A4 junctions near Esch.
- Drivers going to the city also switch to A13→A4 through Esch when A3 is bad, which loads *your* corridor.

**Consequence:** the model has to include the Luxembourg-City-bound demand and the A3/A4/A13/A1 system with queue propagation (spillback). A model of the Belval–Thionville road on its own would be wrong precisely at the moments that matter.

### 2.3 German and Belgian commuters

- **Germany (~53k cross-border workers [V](https://www.aguram.org/wp-content/uploads/2025/09/2025_transfrontalier_memo_04.pdf))**: Saarland commuters come in on the **A13 from Schengen** and drive the whole Collectrice du Sud *westbound through the Croix de Bettembourg* towards Esch/Belval and the south. That's the same choke point as C1. Trier-area commuters use the A1/A7 and matter much less here [K].
- **Belgium (~53k)**: they mostly arrive from the west (A6 Arlon, N5/A13 Pétange). Their flow towards Belval comes from the *other side* (A13 east of Pétange → Sanem → Belval) and competes for the Belval junctions [K].
- **France (~126.6k, +2%/yr [V](https://www.aguram.org/wp-content/uploads/2025/09/2025_transfrontalier_memo_04.pdf))**: the main load on C1–C4, plus Longwy-area flows towards Belval/Pétange.
- Total stock of cross-border workers ~**230,800** (STATEC 2025) [V](https://www.lesfrontaliers.lu/emploi/au-deuxieme-trimestre-lemploi-des-frontaliers-en-hausse-au-luxembourg/). Resident Luxembourgish traffic (Esch, Dudelange, Bettembourg) comes on top.

### 2.4 Proposed modelling perimeter

- **Detailed zone** (lanes, junctions, roundabouts, signals): the Thionville urban area, A31 from Metzange to the border, A30 Thionville–Fontoy, the D-roads of C2–C4, Audun-le-Tiche/Russange/Villerupt/Micheville, Esch/Belval/Sanem, A3 border→Gasperich, A13 Pétange→Schengen, A4 Belval→Hollerich, B40.
- **Simplified zone** (motorways and trunk roads only): A31 Metz→Thionville (this is where the demand forms: ~80–100k vehicles/day north of Metz, 60–70% cross-border commuters, >10k HGV [V](https://www.lesfrontaliers.lu/?p=1222709)), A1/A6/A7, the Luxembourg City ring.
- **Demand zones**: French, German and Belgian communes of residence plus Luxembourg employment zones (Belval, Esch, Cloche d'Or, Kirchberg, Gare, Bettembourg/Contern/Foetz industrial areas, etc.).

---

## 3. Choke points to model explicitly (first inventory)

Starting list, from sources plus local knowledge. Real capacities, observed speeds and queue lengths get measured and calibrated once data flows.

| Choke point | Type | Why it matters | Status |
|---|---|---|---|
| A31 Thionville junctions (Beauregard, Linkling, Terville, Metzange) | merges/weaves on 2×2 | Thionville traffic merges into a motorway already full from Metz. AU66 Beauregard structure carries 83k veh/d, 12% HGV [V](https://paperjam.lu/article/14-semaines-chantier-a-thionvi) | DIR Est maintenance (e.g. 24–27 Aug 2026 [V](https://www.lesfrontaliers.lu/mobilite/des-embouteillages-a-prevoir-autour-de-thionville-la31-perturbee-du-24-au-27-aout/)) |
| A31 Hettange → border (Zoufftgen) | 2×2 section | Lowest capacity on C1 | A31bis north: route validated May 2026, public inquiry May–June 2026, works ~2031, tolled [V](https://info.fr/a31-bis-nord-prefet-moselle-valide-trace-enquete-publique/) |
| A3 border → Croix de Bettembourg | 2×2 → 2×3 works | Queue spillback from the city direction | 2×3 widening due by 2030 [V](https://www.lesfrontaliers.lu/mobilite/vers-5-ans-de-travaux-pour-lautoroute-a3/) |
| **Croix de Bettembourg** (A3/A13) | motorway interchange | The split between city-bound and Esch/Belval-bound flows; German A13 flow crosses it | Being reorganised as part of the A3 works [V] |
| Livange / Dudelange junctions | A3 junctions | Closures during works: Livange closed 30 Oct 21:00 → 2 Nov 04:00, 2026 [V](https://www.lesfrontaliers.lu/mobilite/a3-lechangeur-de-livange-va-a-nouveau-etre-ferme-pour-travaux/); new Livange interchange (lot B2) awarded May 2026 [V](https://bidsfactory.com/en/tenders/mise-a-2x3-voies-de-lautoroute-a3-lot-b2-echangeur-ted-78fb618270b200c3) | Active works |
| A3 Berchem → Gasperich | 2×3 + carpool lane | Opened in 2×3 on 23 Mar 2025, left lane reserved for carpooling (≥2 people) and buses; 06:00–10:00 peak rules; automated enforcement still not live in July 2026 [V](https://paperjam.lu/article/le-premier-troncon-2x3-voies-de-la3-ouvre-avec-une-voie-dediee-au-covoiturage) [V](https://wdocs-pub.chd.lu/docs/exped/2026/07/QP_64352_1784696764325.pdf) | In service |
| A13 Lankelz / Foetz | junctions | Entry point to Esch | [?] |
| **Raemerich** junction (formerly a roundabout) / Belval-Université / Belval-Gare | junction complex | Last bottleneck before Belval; the Belval-Gare ramp towards the city was closed as of 2023 [V](https://wdocs-pub.chd.lu/docs/exped/0145/023/290236.pdf) | Check the current layout [?] |
| Micheville link ↔ A4 | new link | Shifts C2 traffic away from Audun-le-Tiche [V] | In service; flows [?] |
| Audun-le-Tiche / Russange / Villerupt town crossings | urban roundabouts and signals | ~25k veh/d, school zones | N4 Audun–Esch closed 13 Apr–24 May 2026 [V](https://www.lesfrontaliers.lu/mobilite/le-luxembourg-va-negocier-la-creation-dun-bus-transfrontalier-avec-la-france/) |
| Thionville city (Moselle bridges, routes towards Yutz/Basse-Ham, Route de Luxembourg) | urban | Where trips start/end on the Thionville side; few crossings of the Moselle | [?] |

---

## 4. What drives traffic (the full feature list)

### 4.1 Supply (network capacity)
- Geometry: lanes, maxspeed, ramps, weave lengths, roundabout diameter and entries, signal locations (OSM + official datasets).
- **Planned roadworks** (lane closures, junction closures, contraflow, night works), separately for each road authority.
- **Unplanned incidents**: crashes, breakdowns, debris. Detected from DATEX II events and speed drops.
- Speed regimes: dynamic speed limits on the A3, peak-hour rules, hard-shoulder use by buses.
- Carpool lane: available capacity depends on vehicle occupancy and on enforcement.
- Weather affects capacity (rain −5 to −15%, snow −20 to −50%, fog, low sun) [K]. Winter treatment differs on each side of the border.

### 4.2 Demand (who wants to drive, when)
- **Stock**: number of cross-border workers by country, commune of residence, sector and workplace (STATEC, IGSS, INSEE MOBPRO), plus residents. Growth of roughly 1–3%/yr.
- **Daily presence rate** (people actually travelling on a given day):
  - **Telework.** French cross-border workers: 34 days/yr tax threshold, not raised in 2026 [V](https://www.lesfrontaliers.lu/emploi/le-luxembourg-refuse-daller-au-dela-de-25-pour-le-teletravail-des-frontaliers/). Social security limit 49.9% under the EU framework [V]. In practice this gives Mondays and Fridays lighter than Tue–Thu, and the effect varies by month as people use up their 34 days [?].
  - **School holidays in 4 systems**: Luxembourg, France **zone B** (Nancy-Metz academy) [K], Germany (Saarland + Rhineland-Palatinate), Belgium (French-speaking community + Flanders + German-speaking). They overlap only partly. Each country's holidays remove "its" parents.
  - **Public holidays in 4 systems, asymmetric.** For example, **8 May and 14 July** are French holidays but Luxembourg works: French cross-border workers still drive, but local French traffic disappears. **9 May (Europe Day) and 23 June** are Luxembourgish holidays: almost no cross-border commuting [K]. Bridge days come on top.
  - Sickness and strike days, both in transport and general strikes in France.
- **Departure-time distribution**: the shape of the peak, which spreads with congestion (people leave earlier). Flexible hours at Belval (University, LIST) vs fixed shifts (industry, retail, healthcare) [?].
- **Mode split**: car / carpool / train / bus / P&R. Luxmobil 2025: individual car 52.5%, carpool 24.3% of non-walking trips; public transport has its highest share towards Luxembourg City [V](https://gouvernement.lu/fr/actualites/toutes_actualites/communiques/2026/09-septembre/10-backes-luxmobil.html). A dedicated cross-border wave of Luxmobil exists [V](https://transports.public.lu/dam-assets/planifier/enquetes/2025/luxmobil-frontaliers/enquete-de-mobilite-luxmobil-2025-frontaliers-notice-d-information-01092025.pdf). Its detailed tables still have to be found [?].
- **Freight**: >10k HGV/day on the A31 [V]. Different peak hours, Sunday and holiday restrictions in France and Luxembourg, Bettembourg rail-road freight hub.
- **Fuel tourism**: fuel price gaps between FR, LU and DE create trips and stops (Berchem service area, border stations). Luxembourg fuel price changes are announced the day before [K].
- **Events**: Rockhal and Belval venues (University, concerts), Esch, Luxembourg City (Schueberfouer, Kirchberg), Metz and Thionville events, shopping peaks (Saturdays, Christmas, sales periods in FR vs LU).

### 4.3 Rail and bus (substitute *and* shock)
- **Capacity**: Metz–Thionville–Luxembourg TER is the backbone. Region target: 13,500 seats by end 2026 vs 9,000 earlier [V](https://www.lesfrontaliers.lu/?p=1157027). +5% peak seats after summer works [V]. A 1,000-seat train added at 17:15 [V](https://www.lesfrontaliers.lu/?p=1208825).
- **Reliability**: delays and cancellations are visible in GTFS-RT. A cancelled peak train pushes some riders onto the road the next days (behavioural memory) [?].
- **Planned rail closures are the biggest predictable demand shock**: Bettembourg–Luxembourg new-line works. Summer 2026 (mid-July → end Aug) cut Luxembourg–Thionville and Luxembourg–Bettembourg [V](https://luxtoday.lu/fr/transports-et-infrastructures/quelles-lignes-ferroviaires-seront-fermes-en-2026--fr). Further closures planned for 2027 [V](https://www.lesfrontaliers.lu/mobilite/encore-trois-ans-de-travaux-pour-la-nouvelle-ligne-bettembourg-luxembourg/). Replacement buses take road capacity too.
- **Belval specifically**: trains reach Belval via Bettembourg–Esch, *not* directly from Thionville [K]. Rail commuting Thionville→Belval means a transfer at Bettembourg (or a direct train if one exists [?]), which makes it less competitive than for city-bound trips. Re-opening the Longwy–Belval–Thionville rail line is not planned [V](https://paperjam.lu/article/pas-bus-a-haut-niveau-service-).
- **Buses**: RGTR lines 602/603/604 through Audun-le-Tiche to Esch/Luxembourg. Single "RegioZone" fare since 1 Jan 2026. Southern TICE/RGTR network reorganised on 4 Jan 2026 [V](https://www.mobiliteit.lu/en/reorganisation-of-the-tice-and-rgtr-bus-networks-in-the-southern-region-from-4-january-2026/). A cross-border BHNS (bus rapid transit) Micheville–Audun P&R–Esch is under study [V].
- **P&R occupancy** (Frisange, Dudelange, Audun P&R, French stations): if live data exists, it's a leading indicator [?].

### 4.4 Structural changes on the timeline (the model must be time-aware)
| When | Change |
|---|---|
| Mar 2025 | A3 Gasperich–Berchem in 2×3 with carpool lane [V] |
| Jan 2026 | Southern bus network reorganised, RegioZone fare [V] |
| 2026 | Bettembourg rail station works (end of 2026 planned) [V](https://www.lesfrontaliers.lu/mobilite/encore-trois-ans-de-travaux-pour-la-nouvelle-ligne-bettembourg-luxembourg/) |
| →2030 | A3 2×3 up to the French border, Croix de Bettembourg/Livange/Dudelange rebuilt [V] |
| ~2031+ | A31bis north (Richemont→border, 7 km incl. 2.6 km tunnel, ~€1bn, tolled) [V](https://info.fr/a31-bis-nord-prefet-moselle-valide-trace-enquete-publique/) |
| ? | Micheville–Esch BHNS, extra TER after French infrastructure upgrades [V](https://gouvernement.lu/fr/actualites/toutes_actualites/communiques/2025/01-janvier/29-mobilite-cooperation-franco-luxembourgeois.html) |

---

## 5. Data sources

### 5.1 Real-time and historical road state

| Source | Content | Format / access | Coverage | Status |
|---|---|---|---|---|
| **CITA traffic data** (Ponts et Chaussées) on data.public.lu (national access point) | Loop detectors: flow, speed, occupancy | DATEX II, open | A1, A3, A4, A6, A7, A13, B40 | Dataset exists [V](https://data.public.lu/en/datasets/?tag=trafic), docs thin [V](https://cita.lu/en/its.html). Update rate and history depth [?] |
| **CITA traffic events** | Roadworks, incidents, closures | DATEX II v3.6, open | Luxembourg motorways | [V](https://data.public.lu/fr/datasets/cita-evenements-trafic-en-datex-ii-v3-6/) |
| CITA cameras + travel times | Camera snapshots, displayed travel times | Website (cita.lu) | LU motorways | [V](https://data.europa.eu/sites/default/files/use-cases/use_case_luxembourg_-_cita.pdf); scraping rules [?] |
| **DIR Est / Bison Futé** real-time state | Average speed + hourly flow, every 6 min | DATEX II XML, open licence, no login | French **non-concession** national roads: **A31 north of Metz and A30 are free and not concessioned**, so they're covered [K] | [V](https://www.data.gouv.fr/datasets/626113a9e7a3010e25422e7f) |
| Bison Futé events | Roadworks/incidents on national roads | DATEX II situations | FR national network | [?] |
| **travaux.public.lu** traffic orders | Legal orders for each roadworks project (e.g. RM406 A3 Gasperich–Bettembourg) | PDF, scrape | LU | [V](https://travaux.public.lu/circulation/2026/06/RM406_A3_Gasperich-Bettembourg_Travaux_26-06-2026.pdf) |
| Moselle departmental council | Works on RDs (C2–C4) | **No open feed found**, scrape site/news + BOAMP tenders | D-roads | gap [V] |
| Thionville / Esch / Audun municipalities | Urban works, closures | Press releases / city sites | urban | gap |
| **DREAL Grand Est counts** | Annual average daily traffic (TMJA) + HGV per count point, 2017–2024 | Open files | FR roads incl. Moselle | [V](https://www.grand-est.developpement-durable.gouv.fr/IMG/pdf/fiche_methodologique_comptage-3.pdf) |
| TomTom Traffic Flow/Incidents API | Real-time speeds for *every* road incl. D-roads and city streets | Paid, free tier | all | [V](https://www.tomtom.com/products/traffic-apis/) |
| **TomTom Traffic Stats** | Historical speeds and travel times by segment and time slot; this is how we get **history on day 1** | Paid, 30-day trial | all | [V](https://docs.tomtom.com/traffic-stats/documentation/product-information/introduction) |
| HERE Traffic Analytics | Historical speed percentiles | Paid | all | [V](https://docs.here.com/traffic-analytics/docs/ta-rest-api) |
| Google Routes API (traffic-aware) | Door-to-door ETA sampling, good ground truth | Paid per call | all | [K] |
| Waze for Cities | Jams + user reports | Free, but **public bodies only** | all | probably not available to us [K] |

**Key point:** as far as I can tell, CITA and DIR Est publish *live* state, not deep archives [?]. **The collector has to start running on day 1**, because every week not collected is a week of training data lost. Backfill history with a TomTom Traffic Stats trial.

### 5.2 Public transport
| Source | Content | Status |
|---|---|---|
| CFL / mobiliteit.lu GTFS + **GTFS-RT** | Timetables, real-time delays, all LU bus/rail incl. RGTR cross-border buses | [V](https://data.public.lu/en/reuses/gtfs-rt/) (access/stability [?]) |
| SNCF GTFS + GTFS-RT (TER Grand Est) | Real-time trip updates every 2 min + alerts | [V](https://www.data.gouv.fr/datasets/horaires-sncf/informations) |
| Ridership by train | **Not open.** Use published seat capacity + Luxmobil + strike/cancellation events as proxies. Possibly a formal request to Région Grand Est / CFL | gap |
| CFL works calendar | Planned line closures | press/CFL site [V](https://paperjam.lu/article/les-cfl-prevoient-deja-de-nombreux-travaux-ferroviaires-en-2026) |

### 5.3 Demand and structure
| Source | Content |
|---|---|
| STATEC | Quarterly cross-border workers by country of residence [V] |
| IGSS (via AGURAM memos) | Cross-border workers by residence; AGURAM publishes Moselle-level analysis [V](https://www.aguram.org/wp-content/uploads/2025/09/2025_transfrontalier_memo_04.pdf) |
| **INSEE MOBPRO** (home-work mobility detail files) | Commune of residence → country of work for every French commune. **This is the basis for the French side of the OD matrix** [K] |
| Luxmobil 2025 (residents + cross-border wave) | Modal shares, trip durations, departure times [V] |
| Plan National de Mobilité 2040 | Official projections [V](https://gouvernement.lu/dam-assets/images-documents/actualites/2026/09-septembre/10-backes-plan-national-mobilite/doc/dossier-de-presse.pdf) |
| A31bis public-debate files (CPDP) | Traffic studies, peak flows, OD surveys on the A31 [V](https://cpdp.debatpublic.fr/cpdp-a31bis/sites/debat.a31bis/files/synthese-metz-220915_0.pdf) |
| Luxembourg Chamber of Deputies parliamentary questions | Recurring precise figures (counts, works schedules, carpool enforcement) [V] |
| Employers at Belval / Esch | Headcounts and hours (University, LIST, ArcelorMittal, offices); from STATEC/commune data plus estimates [?] |

### 5.4 Context features
| Feature | Source |
|---|---|
| Weather (observed + forecast) | Open-Meteo (free), MeteoLux, Météo-France [K] |
| School / public holidays ×4 countries | Official calendars (LU MENJE, FR education.gouv zone B, DE Saarland/RLP, BE communities) [K] |
| Events | Rockhal, Luxexpo, Rotondes, Metz/Thionville agendas; scraped or hand-entered |
| Strikes | SNCF/CFL alerts (GTFS-RT service alerts), news |
| Fuel prices | LU official daily prices, FR prix-carburants open data [K] |
| Sun position (glare at E–W sections) | Computed |

### 5.5 Geometry and 3D
| Need | Source |
|---|---|
| Road graph, lanes, maxspeed, roundabouts, signals | OpenStreetMap (Geofabrik extracts for LU + Lorraine) [K] |
| Official LU road network | geoportail.lu / ACT [K] |
| Official FR road attributes | IGN BD TOPO [K] |
| Terrain + 3D buildings | LU LiDAR open data, IGN LiDAR HD / RGE ALTI, OSM building heights [K] |

---

## 6. Modelling approach

No single model covers both "predict the next 2 hours" and "what if the Croix de Bettembourg loses a lane". The plan is a **hybrid**:

```
            ┌──────────────── Network model (graph) ────────────────┐
            │ links: lanes, capacity, free speed, jam density       │
            │ nodes: merges, diverges, roundabouts, signals         │
            └───────────────────────────────────────────────────────┘
                 ▲                         ▲                    ▲
  Demand model   │      Supply events      │     Observations   │
  OD matrix ×    │      (roadworks,        │     (CITA, DIR Est,│
  15-min slots,  │      incidents,         │     TomTom, GTFS-RT)
  by mode        │      weather capacity)  │                    │
                 ▼                         ▼                    ▼
  ┌──────────────────────────┐   ┌────────────────────────────────────┐
  │ A. Simulation (DTA)      │   │ B. Statistical / ML forecaster     │
  │ mesoscopic, queues and   │   │ speed/flow per segment, 0-2h and   │
  │ spillback, route + mode  │◄──┤ day-ahead, features from §4        │
  │ choice → what-if         │   │ → nowcast + baseline               │
  └──────────────────────────┘   └────────────────────────────────────┘
                 └──────────── blended forecast + uncertainty ───────────┘
```

**A. Simulation (scenarios, spillback, route shifts)**
- **Dynamic traffic assignment** on the graph (Link Transmission Model or Cell Transmission Model). This captures queue propagation upstream and the bottleneck moving downstream when A3 frees up (§2.2).
- Route choice: logit over C1–C4 (+ city-bound alternatives) using experienced travel times, so diversion onto D-roads shows up.
- Mode choice: logit car / carpool / train / bus, sensitive to train capacity, delays and closures.
- Options: **SUMO** (mesoscopic mode, mature, slow to build networks), **MATSim** (agent-based, heavy), or **our own LTM in Python/Rust**: fast enough to run interactively in the UI. Recommendation: own LTM for the interactive app, SUMO offline to cross-check the choke points.
- Calibration: demand scaled so simulated flows match CITA/DIR Est counts and TomTom speeds by time of day.

**B. Data-driven forecaster (accuracy for "when should I leave")**
- Target: speed/travel time per segment, 15-min resolution, horizons 15 min → 24 h.
- Baseline: gradient-boosted trees with calendar ×4 countries, weather, roadworks, rail state and lagged speeds. Later a spatio-temporal graph network if the data supports it.
- Output: **quantiles (P10/P50/P90)**, not a single ETA. The answer to Q1 is "leave 06:40, P90 = 34 min" vs "leave 07:10, P90 = 58 min".

**Blending:** B gives the forecast under normal conditions. A applies the *change* caused by unusual events (a new roadworks layout, a closure) that B has never seen. Prediction error is shown openly in the app.

**Honest expectations:** in the first weeks (little local history) forecasts lean on TomTom history and simulation. Accuracy improves as our own data collection grows. Rare events (snow, strikes) need months to learn.

---

## 7. The application

### 7.1 Views
1. **3D map (main view)**: MapLibre GL + deck.gl (or CesiumJS) with terrain and buildings. Segments extruded or coloured by speed/flow/level of service; animated vehicle flow particles; queues drawn as growing bands.
2. **Time slider**: replay the past (any day collected) → now → forecast (+24 h). Compare "today vs a typical Tuesday".
3. **Layer toggles**: speed, flow, volume/capacity, roadworks (by authority), incidents, cameras, choke points, rail lines + live train positions/delays, bus lines, P&R, OD flows (arcs from French/German/Belgian communes), weather, events.
4. **Trip planner**: origin/destination (Belval ⇄ Thionville pre-set) → departure-time curve by corridor and mode, with uncertainty bands.
5. **Scenario sandbox**: close a lane or junction, cancel trains, add snow, enable A31bis or A3 2×3, change telework share, then re-run the DTA and see where queues move.
6. **Choke-point dashboards**: each bottleneck with its capacity, demand, queue length and hours above capacity, compared over time.
7. **Model health**: forecast vs actual, data-feed freshness.

### 7.2 Proposed architecture
- **Collectors** (Python, scheduled): CITA DATEX II, DIR Est DATEX II, GTFS/GTFS-RT ×2, TomTom, weather, calendars, roadworks scrapers.
- **Storage**: PostgreSQL + PostGIS + TimescaleDB (time series on segments).
- **Model services**: network builder (OSM → graph + manual corrections for the choke points), forecaster training/serving, LTM simulator.
- **API**: FastAPI (REST + WebSocket for live updates).
- **Frontend**: React + TypeScript + MapLibre/deck.gl.
- Runs locally (Docker Compose) first. Cloud later if needed.

---

## 8. Gaps and risks

| Gap | Mitigation |
|---|---|
| CITA dataset docs thin; history depth unknown | Inspect the feed first; start collecting at once |
| Moselle D-road works have no open feed | Scrape the CD57 site/press + TomTom incidents + manual entry in the app |
| Train ridership not public | Seat capacity + Luxmobil + GTFS-RT disruptions; formal data request |
| Waze for Cities not available to private users | TomTom / Google as substitute |
| Paid APIs (TomTom, Google) cost money | Free tiers + trials for backfill; budget decision needed |
| OSM lane and junction detail may be wrong at key points | Hand-check the ~12 choke points on aerial imagery |
| Telework day-of-week effects not published | Learn from data (weekday residuals) |
| Licences of each feed | Check before any public redistribution; personal use is low risk |

---

## 9. Decisions needed from you (1–3 answered: €0, local only, personal; see §11)

1. **Budget for paid data**: TomTom (Traffic Stats trial + real-time) and/or Google Routes sampling. Without them, D-roads and city streets are blind and there's no history at the start.
2. **Hosting**: always-on collection needs a machine running 24/7 (a home server/NAS or a small VPS).
3. **Main use**: is this for you alone (one commute, personalised) or meant to be shared/public? That changes licensing and polish.
4. **Exact endpoints**: which part of Belval and of Thionville, and which direction/hours matter most to you.

## 11. Revised plan: €0, local, no permanent collector

### 11.1 Feed probe results (2026-11-04, live requests)

**Luxembourg: CITA, all free, no key** (listed on data.public.lu):
| Feed | URL | Content (checked) |
|---|---|---|
| Traffic status per motorway | `https://www.cita.lu/info_trafic/datex/trafficstatus_{a1,a3,a4,a6,a7,a13,b40}` | DATEX II 2.0. For each sensor (`A3.MV.11397` = road + chainage in metres): **lat/lon, direction, avg speed, occupancy %, flow veh/h**. Updated every minute. A3 has ~62 sensors, A13 more. |
| Events v3.6 | `https://cita.lu/info_trafic/datex/situationrecord36` | ConstructionWorks, MaintenanceWorks, obstructions, equipment faults |
| Traffic regulations v3.6 | `https://cita.lu/info_trafic/datex/trafficregulation36` | Speed limits, access restrictions, overtaking bans (~1 MB) |
| Variable message sign travel times | `https://cita.lu/kml/temps_parcours.kml` | Travel times shown on the signs (e.g. "Schengen → LUX-SUD 18 min"): **free ground-truth travel times** |
| Parking (P&R) dynamic/static | `.../datex/parking_dynamic.xml`, `parking_static.xml` | P&R occupancy |
| Weather stations | `.../datex/weather_dynamic.xml`, `weather_static.xml` | Road weather |
| Cameras, interchanges, service areas, tunnels | `https://www.cita.lu/kml/*.kml` | Static layers + camera images |

**France: DIR Est via Bison Futé (tipi), free, no key:**
| Feed | URL | Content (checked) |
|---|---|---|
| Speed + flow | `http://tipi.bison-fute.gouv.fr/bison-fute-ouvert/publicationsDIR/QTV-DIR/qtvDir.xml` | DATEX II, all DIRs, ~1,270 stations, 6-min refresh. **~50 Moselle stations live** (IDs `MZO57.*`, `MZo57.*`, `MZM57.*`, `MZ557.*`) with flow + speed |
| Station reference | `.../QTV-DIR/refDir.csv` | **Problem: most DIR Est rows have no coordinates and no road/PR** (only 2 of 70 filled, e.g. `MZO57.52` = A31 PR 290). Fix: place stations by hand once (match ID pairs and direction to A31/A30 positions, check against flow continuity), stored in a small hand-edited file |

**Also free:** OSM (Overpass / Geofabrik), CFL and SNCF GTFS (+ GTFS-RT), Open-Meteo (weather forecast + history, no key), holiday calendars (static files), DREAL Grand Est counts (annual averages), INSEE MOBPRO (commuter origin–destination).

**Dropped:** paid TomTom/HERE/Google. Optional: the TomTom *free tier* needs your own personal key and gives live speeds on D-roads and city streets. Without it, C2–C4 and Thionville/Esch city streets have **no live data**: they're simulated, calibrated with annual counts.

### 11.2 Consequences for prediction
- **No history at the start.** Forecasts begin from a **model prior**:
  - typical weekday demand profiles, built from count data, the commuter origin–destination model and the calendars (holidays ×4 countries, telework);
  - pushed through the traffic simulation, which gives speeds and queues.
- **The app records while it runs.** Every snapshot fetched while the app is open (CITA every 1 min, DIR every 6 min) goes into a local SQLite/DuckDB file. Over weeks that becomes a real history, and the forecaster (§6 B) takes over gradually. Data quality and coverage are shown in the app.
- **Optional later:** the same collector script on the Raspberry Pi gives a gap-free history. One command, no change to the app.

### 11.3 Local stack (one command to run)
- **Backend:** Python + FastAPI, a single process. Fetches feeds on demand (cached), stores snapshots in a local DB file, runs the simulation and the forecaster.
- **Frontend:** React + TypeScript + Vite, MapLibre GL + deck.gl for the 3D map. Free base map tiles (OpenFreeMap / OSM-based), free terrain.
- **Static data** (OSM network, stations, calendars, origin–destination model) built once by a script into `data/`.
- No Docker, no database server, no cloud.

## 10. Proposed phases (superseded by §11.4)

### 11.4 Revised phases
1. **Live observatory**: backend reads CITA + DIR Est (+ CITA events/regulations/travel times/P&R); DIR stations placed on the map; 3D map with live speeds, roadworks, cameras, choke points; snapshots recorded while the app runs.
2. **Network model**: corridor graph from OSM (C1–C4 + upstream A3/A4/A13), choke points hand-checked, capacities.
3. **Demand + simulation**: commuter origin–destination model + calendars → the traffic simulation reproduces a typical morning and evening, calibrated to CITA/DIR flows.
4. **Forecast + planner**: departure-time curves by route and mode (trains from GTFS/GTFS-RT), with uncertainty; recorded data blended in as it accumulates.
5. **Scenarios**: close lanes or junctions, cancel trains, snow, A31bis/A3 2×3.

### Original phases

1. **Phase 0, data probe (days)**: connect to CITA and DIR Est DATEX II, GTFS-RT; check which segments, fields and refresh rates actually exist; **start the 24/7 collector**.
2. **Phase 1, network + observatory**: build the graph for the perimeter, choke-point inventory, 3D map with live state + roadworks + trains, replay.
3. **Phase 2, demand model**: OD matrix from MOBPRO/STATEC/IGSS, calibrated to counts; first LTM run reproducing a typical morning.
4. **Phase 3, forecaster**: quantile model on collected + backfilled history; trip planner.
5. **Phase 4, scenarios**: sandbox, structural changes (A3 2×3, A31bis, rail works), mode shift.
