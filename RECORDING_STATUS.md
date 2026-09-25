# Recording status: final 3–5 minute demo

*Prepared 2026-09-25. Claude did not record, upload or publish any video. Everything below was checked on this machine at preparation time, and the checks are listed in §2.*

## 1. Does an actual video file exist?

| Location | Finding |
|---|---|
| Project folder `C:\Users\yugra\source\hhgoa-fraud-agent` | **No video file.** |
| `C:\Users\yugra\Videos\Captures\ChatGPT 2026-09-25 02-01-05.mp4` | A video file exists. It was **not opened or verified**; the name suggests a Game Bar capture of a ChatGPT window, not this demo. |
| `C:\Users\yugra\Downloads\6ab509c5b7036_ml_challenge_2026_video.mp4` | A video file exists; the name suggests a different project. Not opened. |
| `SOCIAL_POST_DRAFT.md` | Contains a Google Drive video link that you added. Its contents were **not verified** by Claude. |

**Status: no demo recording has been verified. Record it using §4, then check it using §5.**

## 2. Verification of the demo setup (run at preparation time)

| Check | Result |
|---|---|
| Streamlit app at http://localhost:8501 | **Running.** `/_stcore/health` returns `ok`, the page returns HTTP 200, and the launch log has 0 errors |
| UI, all 20 cases (headless test) | Render with no exceptions; the six section headings and anchors are unchanged |
| HHG-017 flow | Shows as_of `2016-11-12 00:46:24`, flagged `3450629`, card `C04570-K1`, 8 provenance rows, 7 evidence rows, p 0.34 → 0.03, SIMULATED "customer confirms", verdict legitimate, graph case `INV-HHG-017-0e29f8b20a`, audit `verified · 42 events` |
| HHG-014 flow | Shows as_of `2016-11-22 20:11:00`, flagged `3478561`, the device-ring claim (19 other customers' cards), pattern `undocumented`, p 0.51, SIMULATED "no reply within 24 hours", final DECLINE_TRANSACTION (L1), CREATE_CASE, FILE_REPORT (L2), MONITOR_CARD, MONITOR_CONNECTED_CARDS, ESCALATE_TO_ANALYST, graph case `INV-HHG-014-8b1a484af8`, audit `verified · 49 events` |
| Test suite | `Ran 77 tests … OK` |
| Verifier, offline checks (`--no-graph`) | **20/20**: schema, IDs against the raw data, as_of cut-off, exposure, SAR, routes, policy reproduction, audit chain, provenance |
| Verifier, full (with TigerGraph read-back) | **Could not run today.** The Savanna workspace returns *500 Internal Server Error* on GSQL, REST++ and the token endpoint |
| Saved full-verification report `reports/phase2_verification.json` | Says `exact_file_set: true`, `cases_passed: 20` from the last successful full run. It is identical to the committed version (commit `67168cc`) |

**Before recording the verifier segment:** resume the workspace in the Savanna console, then run the command in §4, step 9. If it still fails, **do not show the error on screen** (the error text contains the workspace host). Instead, show the saved report, and use the fallback narration in §3.

### 2a. Re-check later on 2026-09-25

| Check | Result |
|---|---|
| Test suite | Re-run: `Ran 77 tests … OK` |
| Architecture checks | Re-run: `51 passed, 0 failed` |
| `cases/` | Exactly `HHG-001.json` … `HHG-020.json`. Verdicts: 8 fraud · 11 uncertain · 1 legitimate |
| Streamlit app at http://localhost:8501 | **Not running** (the health check got no response). Start it before recording (§4, step 2) |
| Full verifier with TigerGraph read-back | **Not re-run.** Savanna availability was not re-checked. Both verifier modes overwrite `reports/phase2_verification.json`. The committed report is unchanged and still says 20/20 |
| Video | Still **no video file** in the project folder. The Drive link in `SOCIAL_POST_DRAFT.md` and `TECHNICAL_BLOG_DRAFT.md` has **not been verified** |

Also note: the X/Twitter versions in `SOCIAL_POST_DRAFT.md` say "20/20 cases pass". That comes from the last full run in the saved report, not from a run today. If the live verifier can't run before posting, use the fallback wording from §3.

## 3. Narration timing (read from DEMO_SCRIPT.md; do not change any numbers)

| Time | Screen | Key narration |
|---|---|---|
| 0:00–0:25 | Page top: **SIMULATED ENVIRONMENT** banner + KPI cards | Agentic fraud investigator on TigerGraph Savanna, deciding under the bank's policy R1–R10 and writing each case back to the graph. **"Customer replies, actions, approvals and reports are simulated."** |
| 0:25–0:55 | HHG-017 → **1. Case input** | Model alert on transaction 3450629, $100.09 online, score 0.57; as_of 2016-11-12 00:46:24; every query is forced to that moment. |
| 0:55–1:40 | **2. Graph evidence and provenance**: **Graph calls** tab, then click the **Evidence** tab (graph calls, evidence and entity graph are separate tabs) | 8 graph calls through the gateway to the official TigerGraph MCP server, each with the injected as_of and a result hash; the risk score is an input with zero weight; no shared-origin link; familiar amount, product and device. |
| 1:40–2:10 | **3. Assessment and initial decision** | Scorer calibrated on 300 closed cases; base probability 0.34 with no independent evidence, so R1 applies (verify before blocking); initial VERIFY_WITH_CUSTOMER + CREATE_CASE (auto, §3a). |
| 2:10–2:35 | **4. Additional evidence (SIMULATED response)**: amber SIMULATED panel | **"The dataset has no customer replies. This response is SIMULATED"**: a deterministic assumption, customer confirms, because 0.34 ≤ 0.40. |
| 2:35–3:05 | **5. Final decision, approval routes and report** | p 0.03, legitimate; CREATE_CASE + CLOSE_NO_FRAUD (R3); no SAR (§3a); what changed 0.34 → 0.03. **"Execution and approvals shown here are simulated."** |
| 3:05–3:35 | **6. Audit trail and graph persistence** (open the expander briefly) | Hash-chained audit log of 42 events, verified; case INV-HHG-017-0e29f8b20a written through the official MCP and read back byte for byte. |
| 3:35–4:25 | Sidebar button **HHG-014 ring** → section 2 (**Entity graph** tab) and section 5 | 19 other customers' cards on the same fully specified device profile within 30 days; cites CC-2649/2971/2985/3035; undocumented ring; R6/R9 actions; FILE_REPORT awaits L2 and DECLINE_TRANSACTION awaits L1, both **simulated**; the verdict stays uncertain at 0.51. |
| 4:25–4:50 | Terminal | **If the live verifier passes:** "All 20 answer files pass an independent verifier, 20 out of 20, including the TigerGraph read-back." **Fallback if Savanna is still down:** "The offline checks pass 20 out of 20 today; the last full run with graph read-back also passed 20 out of 20, as saved in the committed report." Show `--no-graph` output + `reports/phase2_verification.json`. |
| 4:50–5:00 | Page top | Closing: 8 fraud · 11 uncertain · 1 legitimate; limitations are in the blog; **all customer-facing actions are simulated**. |

## 4. Windows / OBS recording steps

**Prepare the machine (5 minutes)**
1. Turn on **Do not disturb** (Settings → System → Notifications) and close chat, email and any window showing credentials. Do **not** open `.env`, `data/raw/`, `runs/build/` or the Savanna console credentials page while recording.
2. Browser: open http://localhost:8501 in a clean window with the bookmarks bar hidden and zoom at 90–100%. Select **HHG-017 demo** in the sidebar. If the app isn't running, start it from Git Bash:
   ```bash
   cd /c/Users/yugra/source/hhgoa-fraud-agent
   .venv/Scripts/streamlit run ui/app.py
   ```
3. Terminal (Git Bash) for the last segment: `cd /c/Users/yugra/source/hhgoa-fraud-agent`, then `clear`.

**Install and configure OBS Studio** (not found at `C:\Program Files\obs-studio`)

4. Download OBS Studio from https://obsproject.com and install it with the default options.
5. OBS → **Settings**:
   - **Video:** Base and Output resolution 1920×1080; 30 FPS.
   - **Output → Recording:** format `mp4` (or `mkv`, then use File → Remux Recordings to get mp4); encoder: hardware (NVENC/QuickSync/AMF) if listed, otherwise x264; recording path `C:\Users\yugra\Videos`.
   - **Audio:** Mic/Auxiliary = your microphone; set Desktop Audio to *Disabled* unless needed.
   - **Hotkeys:** Start Recording `Ctrl+Shift+R`, Stop Recording `Ctrl+Shift+S`.
6. Scene: Sources → **+** → **Display Capture**, choosing the monitor that shows the browser and terminal. (**Window Capture** of the browser is also fine; switch to a second scene with a Window Capture of Git Bash for the last segment.)
7. Test: record 10 seconds, play it back, and check that the audio level is clear and the text is readable.

**Record**

8. Press `Ctrl+Shift+R` and follow §3. The target length is 4:00–4:50, and it must stay within 3:00–5:00.
9. Verifier segment. Run exactly this command: it masks secrets **and** the workspace host.
   ```bash
   PYTHONPATH=src .venv/Scripts/python scripts/verify_cases.py 2>&1 | .venv/Scripts/python scripts/redact.py | sed -E 's#https://[^ /]+#https://<workspace-host>#g' | grep -v Deprecated
   ```
   If it fails, run the offline fallback instead, then show the saved report:
   ```bash
   PYTHONPATH=src .venv/Scripts/python scripts/verify_cases.py --no-graph
   git checkout -- reports/phase2_verification.json
   cat reports/phase2_verification.json
   ```
   The `git checkout` restores the committed full-run report, which the offline run overwrites.
10. Press `Ctrl+Shift+S`. The file is saved in `C:\Users\yugra\Videos`.

**Windows Game Bar fallback:** `Win+Alt+R` starts and stops recording of the focused window only, and saves to `C:\Users\yugra\Videos\Captures`. It can't follow you from the browser to the terminal, so record the terminal segment as a second clip or skip it and use the fallback narration.

## 5. Final checklist (tick before publishing)

- [ ] The recording **says aloud** that **customer replies are simulated**.
- [ ] The recording **says aloud** that **actions are simulated** (auto actions run only in a sandbox with no network clients).
- [ ] The recording **says aloud** that **approvals are simulated** (L1/L2 items only "await approval").
- [ ] The recording **says aloud** that **SARs are simulated** and not filed with any regulator.
- [ ] The SIMULATED ENVIRONMENT banner, the amber SIMULATED panel in section 4 and the SIMULATED labels in section 5 are visible on screen.
- [ ] Nothing is described as a "confidence" score. The UI has no confidence card, because the answer files have no confidence field.
- [ ] No `.env`, credentials, raw data (`data/raw/`), build logs (`runs/build/`) or workspace hostname appear anywhere in the video.
- [ ] Numbers spoken match the UI and DEMO_SCRIPT.md (HHG-017: 0.34 → 0.03, 42 audit events; HHG-014: 19 other customers' cards, 0.51, 49 audit events; totals 8 fraud · 11 uncertain · 1 legitimate).
- [ ] The verifier claim matches what was actually shown: the live 20/20 only if the full run passed on camera, otherwise the fallback wording.
- [ ] No accuracy or production claims are made. The limitations (1 legitimate of 20; the "no reply" band; scorer backtest caveats) are mentioned or referenced.
- [ ] Length is between 3:00 and 5:00. The video was watched once end to end before sharing.
- [ ] The final video file is saved locally, and its path is recorded in this file before you publish it yourself.
