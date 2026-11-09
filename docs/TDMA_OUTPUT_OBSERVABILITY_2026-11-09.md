# Mechanical output observability — 2026-11-09

New relation: `mechanical_output_unobserved_hypothesis`. This is an inspection hypothesis, not a confirmed mechanical-decoupling diagnosis. Electrical activity, valid vibration and observed positive motor RPM with stale Hall output in a configured direct-drive setup can raise an alert without a calibrated current curve. Missing/invalid measurements are not measured zero. Alternatives include mechanical decoupling and Hall acquisition/positioning failure. Protrusion is not directly measured. Causal confidence is unquantified (`confidence_permille=0`); consumers must not present it as a calibrated probability.

Existing calibrated decoupling and temporal validity rules remain. No OS 1156 historical payload was rewritten and no new capture was started automatically.

Firmware signature/UI native suites and the ESP32-S3 UI4 build passed. Application-only flash at 0x10000 was authorized, written and verified; bootloader, partition table and NVS preserved. Application SHA-256: `9ae9130c74bf7258f6798ef1001488074ff1835938638cc1cc306832153bfd0e`. Encrypted recovery copy and separate key remain private on Linux. Serial responded after restart; real fault/sensor-disconnection validation still requires controlled captures.

Cous: 187 tests passed. Existing interactive process must be reopened to load the change. OpenTracy: 48 targeted tests passed; service restarted and health/worker availability checked. Post-restart queue check: zero pending/processing. Initial pre-restart environment check omitted Python dotenv and cannot prove the previous queue state. SystemOS: 18 telemetry tests, API build and typecheck passed; source committed on a correction branch, not deployed to production in this step. No push performed here.
