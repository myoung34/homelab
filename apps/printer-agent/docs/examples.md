# Example queries

What the agent does for common questions. Tool names in brackets.

| Ask | What happens |
|---|---|
| Why did my Ender 5 stop during the last print? | [`printer_what_happened` which=last_failed] Builds a timeline, reports the proximate cause (OBSERVED), ranks root causes, gives the next test |
| Why did the print fail at 63%? | Same, for that job; progress at end comes from filament used vs total |
| What was happening immediately before the shutdown? | [`printer_logs` mode=events] The G-code dump before the shutdown, plus Stats temperatures and MCU link |
| Show me the last 10 failed prints and classify them | [`printer_classify_failures`] Class and domain per job, with the log line as evidence |
| Why does G28 fail intermittently? | [`printer_diagnose`] Probe/homing workflow: error frequency across sessions, config checks, fleet comparison, live QUERY_ENDSTOPS |
| Why is my BLTouch failing to trigger? | Same, then suggests `printer_probe_query` (no motion) |
| Is my extruder temperature behaving normally? Is my bed stable? | [`printer_temperatures`] Stability, oscillation, power headroom, impossible jumps |
| Is this printer ready to print? | [`printer_readiness`] `{ready, blocking, warnings, recommendations}` |
| What changed since the last successful print? | [`printer_config_diff` base=known_good] Risk-classified diff; plus [`printer_git_log`] for the seed |
| Does Git match the printer? | [`printer_config_drift`] Seed vs on-disk vs running config |
| Compare enderleft with enderbig | [`printer_compare`] |
| What should I calibrate next? | [`printer_calibration`] Ranked, with evidence; flags values copied from another printer |
| Analyze this G-code / why did this print home twice? | [`printer_gcode_inspect`] Includes homing hidden in macros and invalid `BED_MESH_CALIBRATE` params |
| Analyze this Klipper log | [`printer_logs`] |
| Make the change / show me the diff | [`printer_config_propose`] Diff, computed risk, validation. Nothing applied |
| Apply it | [`printer_config_apply`, approval] Backup, upload, RESTART, verify running config, rollback on failure |
| Commit it | [`printer_config_open_pr`, approval] PR syncing the Git seed; you merge, Argo CD syncs |
| Home Z / heat the bed to 60 | [`printer_home` / `printer_set_temperature`, approval] Verified by reading back |

## What it finds in today's configs

Verified by running the analysis code against the seeds in `k8s/prod/klipper`
and the PrusaSlicer profiles in `myoung34/dotfiles`:

- `verify_heater extruder` has `max_error: 12000000` and `hysteresis: 50` on
  all three printers: thermal runaway protection is effectively off (`danger`).
- The saved bed meshes on enderbig (1.70 mm range, X slope -1.53 mm) and
  enderright (1.64 mm, +1.19 mm) are dominated by a consistent tilt that the
  mesh is compensating; screws tilt comes before re-meshing or Z offset.
  enderleft's is 0.64 mm.
- enderright's PID values are identical to enderleft's (the seed was copied).
  They're `inherited`, not calibrated.
- The PrusaSlicer start G-code runs `BED_MESH_CALIBRATE LOAD=default`. `LOAD`
  isn't a parameter of that command, so it re-probes every print. If reuse was
  intended, the command is `BED_MESH_PROFILE LOAD=default`.
- With `gcode_flavor = marlin`, M201/M203/M205 are ignored by Klipper.
  PrusaSlicer has a `klipper` flavor.
