## KPCL Energy Dashboard + Plant Alert v2.1

All data is a benchmark-calibrated **simulation**, not real KPCL readings.

### Dashboard
- **Every chart explains itself.** Click any chart or diagram (or its ⓘ) for a card saying what it shows,
  how to read it, and what the data on screen right now implies — 22 charts across all 8 pages, including
  the What-if simulator and Baseline vs optimized.
- **3D Facility View** on the Live Monitor: Hadapsar / Saswad / Nashik rooms with low-poly machines
  coloured by live state (green running, yellow idle, red pulsing fault). Click a machine for its rating,
  power draw, load and active faults. Fault visuals: furnace door swings open and turns red, CNC idle drift
  dims its indicator, weekend base-load waste lights the compressor room amber. Scroll-zoom only after you
  click into the view, so the page still scrolls. Loaded on demand, so the rest of the dashboard stays light.
- Fixed sideways scrolling on phones (Live page controls, plant comparison table).

### Phone app (APK below)
- Same app as v2.0 (critical-only alerts, developer console), version number aligned to 2.1.
- Needs the matching server: run `run-demo.ps1` from this release's code.
