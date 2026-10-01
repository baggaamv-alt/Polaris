# Plan: stabilise the simulator, then add a 3D globe map

## Step 1: Stabilise (do first)
- **Revert the unfinished road-curvature and GPS-multipath change** in `backend/pnt1/world.py` and `backend/pnt1/config.py`. It used Python `hash()`, which changes on every run and broke reproducibility.
- **Switch the anomaly model off.** The first training run's drift results relied on a simulator artefact (perfectly straight roads), so the model is not trustworthy yet. Move `backend/models/anomaly_iforest.*` aside and keep the training code for later.
- **Done when:** the backend tests pass and the statistical check shows "not active" again.

## Step 2: Minimal globe (frontend map only)
1. Upgrade MapLibre GL JS from 4.7.1 to 5.x (CSS + JS).
2. Control-room map: globe projection, atmosphere halo, near-black space background with a static CSS starfield.
3. Base layer: Esri World Imagery satellite tiles with correct attribution. The existing land-only base remains the fallback.
4. Remove `maxBounds`. Start centred on India at zoom about 2.2.
5. Recolour routes for contrast on dark imagery: idle routes light warm grey, active routes bright steel, labels light with a dark halo. Blocked and suspected keep their hues, with a stronger casing.
6. Add a Globe/Map toggle to the existing map controls, remembered in localStorage.
7. Handle v5 API differences, e.g. `getClusterExpansionZoom` returns a Promise.
8. **Done when:** the globe loads centred on India; trucks, clusters, selection, popups and the legend work; no console errors.

## Out of scope (to save usage)
- Reference-labels overlay
- Globe for the Scenario lab's cascade map (it stays flat)
- Deep performance tuning
- Retraining the anomaly model with realistic GPS noise (a follow-up)

## Risk
If the v5 upgrade breaks something unexpected and usage runs out, Step 1 still leaves the app in its last verified working state.
