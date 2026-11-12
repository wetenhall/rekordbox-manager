# Rekordbox Manager

Prepare Rekordbox playlists with beat-grid review, editable drop markers, and
memory cues every 16 bars before your drops. Preview changes with a waveform and
audio playback, then import supported edits with automatic backups. All processing
runs locally on your computer.

## Download

**Published download: Preview 0.3.73 — no Python installation required.**

The downloads and this source checkout include the changes described below.

| Your computer | Download | Requirements |
| --- | --- | --- |
| Windows PC | [Download for Windows](https://github.com/wetenhall/rekordbox-manager/releases/download/v0.3.73/Rekordbox-Manager-0.3.73-Windows-x64.zip) | Windows 10/11, x64; analysis and preview only |
| Mac with Apple chip (M series) | [Download for Mac — Apple Silicon](https://github.com/wetenhall/rekordbox-manager/releases/download/v0.3.73/Rekordbox-Manager-0.3.73-macOS-Apple-Silicon.zip) | macOS 12.3 or later |
| Mac with Intel processor | [Download for Mac — Intel](https://github.com/wetenhall/rekordbox-manager/releases/download/v0.3.73/Rekordbox-Manager-0.3.73-macOS-Intel.zip) | macOS 12 or later |

[Release notes and checksums](https://github.com/wetenhall/rekordbox-manager/releases/tag/v0.3.73)
· [All releases](https://github.com/wetenhall/rekordbox-manager/releases)
· [Report a problem](https://github.com/wetenhall/rekordbox-manager/issues)

Choose **Apple menu → About This Mac** to check your Mac's chip/processor.
Download an app ZIP from the links above, rather than GitHub's source-code ZIP.
The releases are portable packages: extract the full download before opening it.

**Compatibility:** saving grids and cues is enabled only for **Rekordbox
7.2.19.0342 on macOS**, with supported local MP3/WAV tracks. Windows and other
Rekordbox versions remain **read-only**. Automatic drop suggestions need your
review. This is a preview, not a claim of general compatibility with every library.

![Rekordbox Manager showing drop markers and memory cues on generated demo audio](docs/images/playlist-preview.png)

*Preview with generated test audio; no personal library or commercial music is shown.*

## Built-in functions

### App tabs and Organiser

- **Manager** keeps the existing playlist, cue and grid workflow. **Imports**, **Organiser**,
  **Backups** and **Settings** have their own tabs at the top right of the header.
  Switching tabs preserves
  Manager edits and pauses its playback; transport shortcuts only work in Manager.
- In **Organiser**, choose **Scan library** to read every active collection track,
  including tracks outside playlists. Scanning runs in the background, can be cancelled,
  and does not decode audio or change the database, cues or playlists.
- Organiser shares Manager’s playlist/folder browser and compact striped track table.
  Select a playlist to browse its scanned tracks, or **All library tracks** to return
  to the collection. Usage columns show plays, history, playlist count and status.
- The default **No regular playlists** view finds unfiled tracks, regardless of play count.
  Tick tracks individually or use **Select all matching**, across all pages.
  Selections persist through search, filters and pagination; the count identifies selections
  off the current page. **Clear selection**, a new scan or changing libraries clears them.
- Use **New folder** or **New playlist** below the browser to create session drafts.
  Choose the parent folder, including another draft folder. Creating a playlist can
  include the selected scanned tracks. Drafts appear in the browser with a “draft” suffix.
- Left-click a folder’s name for **New subfolder…** or **New playlist…**; the arrow
  still expands/collapses the folder. Right-click provides the same actions.
- Drag a playlist or folder onto a folder to nest it, between rows to reorder it,
  or onto empty browser space to return it to the top level. Folder contents move
  together. Clear the playlist search before dragging. Self/descendant moves are blocked.
- Moves and order changes are drafts too: review and apply them in **Imports → Playlist changes**.
  Existing track membership and track order inside playlists are preserved; only the
  reviewed folder hierarchy and playlist/folder order change.
- **Queue in playlists…** assigns selected tracks to existing or draft playlists.
  Tracks already in playlists can also be selected; their existing memberships are kept.
  Repeated assignments are deduplicated. No database writes occur while organising.
- In **Imports**, choose **Playlist changes**, review the new folders/playlists, moves/order changes and every
  track assignment, then click **Import playlist changes**. This is separate from the
  **Cues & beat grids** import view. Both queues survive the other kind of import.
  A verified backup covers the database and existing `masterPlaylists6.xml` metadata;
  failed installation restores both. The organiser rescans after import.
- Drafts are stored for this app session only. Import before closing/reconnecting, or
  use **Discard playlist changes**. Closing, reconnecting and restore check for drafts.
- Audio files are never moved, renamed or rewritten. Comments, cues, grids, existing
  memberships and existing playlist order are preserved. Additions require Rekordbox to
  be closed, an unchanged scan and local unsynced content/playlists. Unsupported versions
  remain scan-only. Pending cue/grid preparations remain in Imports.
- Playlist additions are experimental and gated to Rekordbox **7.2.19.0342 on macOS** with
  the supported schema. Plain/encrypted fixture tests cover preservation, stale inputs,
  rollback and byte-exact restoration. Native Rekordbox reopen/export behaviour for these
  new membership writes has not yet been verified; grid/cue verification does not establish it.
- Other filters include **No recorded plays**, **No recorded plays + outside playlists**,
  **Played**, **Unknown play status**, or **All tracks**. Search title, artist and genre,
  and sort by title, artist or play count. Results show 100 tracks per page.
- Each result shows its recorded play count, saved history entry count and number of
  distinct regular playlists. A positive count or history entry means recorded use.
  A zero count without history in the available data means **No recorded plays**.
  Missing or invalid play counts without history remain **Unknown**.
- These are recorded usage signals, not proof that a track has never been played.
  Reset counts, removed history and unsynced device plays can hide use. Smart playlists
  are excluded from membership, and missing history data is explicitly reported.
- Results show their scan time. Changing libraries, importing edits or restoring a
  backup clears them. If the database changes outside the app, reconnect in Settings
  before rescanning. Usage scanning requires a real Rekordbox database, not the demo.
- Add future features as separate page widgets in `MainWindow.build_workspace()`;
  keep their state and workers in their own modules, as `organiser_ui.py` and `usage_ui.py` do.

### Check existing cues in Manager

Choose a playlist in the browser, select **Check saved cues** beside the scan action,
then click **Check playlist cues**. This reads saved memory points and compares them
with independently suggested drops and 16-bar countdowns. It never writes cues,
changes grids, or adds check results to Imports. Existing preparation drafts are retained.
The Manager skip/replace options apply only in **Prepare tracks** mode.

- **Cues match** means the timings match within the selected tolerance (50 ms by default),
  not that musical correctness is guaranteed. Names are ignored; matches are one-to-one.
- **Cue differences** identifies missing suggested positions or saved points outside the pattern.
- **Inconclusive** means detection needs a human check; **Unavailable** means analysis failed.
- **No memory cues** includes tracks with only hot cues or loops. These are not comparison errors.
- Use **Flagged only** or **Cue differences** to narrow the playlist. Red triangles in row previews
  show saved memory cues. The upper **Original** waveform shows saved cues/grid; the lower
  **Proposed** waveform shows editable suggested cues/grid. Zoom, scrolling and the playhead
  stay linked. Playback is available after a successful check.
- Row cue positions are visible before scanning; bass-focused waveform previews load
  automatically in the background for every track in the selected playlist.
- Checks run sequentially for the selected playlist(s), with a compact overview per result.
  Cancel stops after the current track; remaining tracks stay **Not checked**. A bounded
  session cache reuses up to 256 unchanged results, invalidated by source metadata, saved
  cues/grid or tolerance changes. Reconnecting clears the cache; it is not a saved audit report.
- Hot cues and memory loops are not compared or replaced. Saved loops still consume the
  ten-slot memory budget when generating the app pattern.
- **Drop 1 / Drop 2** and their Zoom buttons show the suggested anchors immediately after checking.
  Saved cues appear in red on Original, with suggestions in amber on Proposed.
  **Keep original cues** and **Replace cues** sit alongside **Rebuild cues**; the extra
  comparison controls and explanatory strip have been removed. Track filters, counts and
  scan progress belong to the playlist toolbar below the waveform in both modes; switching
  modes never adds a row above the waveform. Drop controls keep the same sizing in both modes.
- Suggested drops are editable immediately when you select a successfully checked track;
  there is no separate activation button. Editing uses an independent replacement draft.
  Adjust the drop fields or drag the amber handles, use **Rebuild cues** after edits, then
  **Replace cues**. This adds only that track to **Imports**; the final import
  replaces its memory points while preserving hot cues, loops and playlist membership. The
  saved grid is retained unless you explicitly shift it; the action then reads **Use cues + grid**.
  **Keep original cues** leaves saved cues unchanged, removes any queued preparation for that
  track, and marks it resolved in the check results. This choice survives playlist browsing
  in the current session while the checked source is unchanged. You can still choose
  **Replace cues** later. Keeping originals cannot undo an import already completed.
  Queued replacements lose their yellow review highlight and leave **Flagged only**.
  Further edits restore the highlight and revoke readiness until rebuilt and confirmed again. A changed source must be checked again.
  Inconclusive suggestions require listening and review; they are not automatically correct.
  Unconfirmed comparison drafts are cleared when the playlist, mode or tolerance changes.
  Confirmed replacements stay in the session import queue; source files change only on import.

### Manual grid adjustment

**Beat grid ‹ / ›** appears beneath the drop controls in both Manager modes. Each click shifts
all beat timings by 10 ms; Shift-click shifts by 1 ms. BPM and drop markers stay fixed.
Only the selected proposed track changes. **Rebuild cues** retains this manual grid position,
then confirm/accept before importing. **Align to Drop** explicitly resumes automatic alignment.
The original waveform remains read-only. **Keep original** removes the queued cues and grid.
Nudges support constant-tempo grids, up to half a beat from the original, with at most one
out-of-audio boundary beat trimmed. Reversing the nudge restores that beat. Variable tempo
or incorrect BPM still needs correction in Rekordbox.

### Imports across playlists

The queue uses the same compact, alternating track rows as Manager, with columns
for planned changes, source playlists and import status. Select a row and choose
**Review in Manager**; the import action sits below the list.

- Prepare playlists one at a time or together in **Manager**, then open **Imports**.
  Ready tracks collect automatically across playlist changes, deduplicated by Rekordbox
  content ID. The latest preparation replaces an earlier draft of the same track.
- Each row shows the track, artist, planned cue/grid operations and source playlists.
  Search by track, artist or playlist; use **Needs review** to find blocked preparations.
  **Review in Manager** returns to the saved preparation, including manual marker edits.
- **Import all ready tracks** includes the whole queue, even rows hidden by search.
  Its final confirmation shows the source-playlist breakdown. Tracks needing review
  are excluded; cancelled or failed imports keep the queue available for retry.
- Imports update existing track IDs. Playlist membership, folders and track order
  are preserved. Shared tracks update in every playlist containing them; different
  playlists cannot have separate grids or cues for the same content ID.
- Changed database, audio or analysis files block stale imports. Every successful
  batch uses the existing verified backup and import process; remaining preparations
  can be reviewed and imported in a later batch.
- The queue is session-only. Closing or reconnecting prompts before discarding pending
  work. Restoring a backup clears preparations. Nothing is imported automatically.

### Library and playlist browsing

- Open an existing encrypted Rekordbox 6/7 `master.db` without an XML export.
- Detect the usual database location or choose a custom location manually.
- Load regular playlists with their parent-folder names and original track order.
- Use the left-hand playlist browser below the waveform to navigate the saved
  Rekordbox folder hierarchy and sibling order. Empty folders remain visible; smart
  playlists are shown but cannot be scanned. Search by playlist or folder name, and
  drag the divider to resize the sidebar. Use **Select multiple…** to select
  several playlists, then **Scan & prepare playlist**. Search matches words across playlist
  and folder names and reveals matching branches automatically. **Selected only**
  shows your batch; hidden selections remain checked and are counted. **Select visible**
  selects all matching playlists, including those in collapsed folders.
  Shared tracks appear once in the combined review and import. Prepared tracks stay in
  Imports when the selection changes. Returning to a fully prepared selection restores
  its drafts; preparing it again replaces those queued drafts.
- Import confirmation lists each scanned playlist with Scanned, Import and Skip counts
  (plus already Imported counts after a partial import). Shared tracks count in each
  playlist but are imported once. Imports are blocked if results or playlist selection
  no longer match the original scan. Cues and grids belong to tracks, so changes also
  appear wherever those tracks are used; playlist membership is unchanged.
- **Show details** opens a scrollable
  list of tracks and review reasons; skipped tracks are left unchanged.
- Display track title, artist, genre, BPM, duration, existing cues and analysis issues.
- Change the connected library from the workspace.
- Check for Rekordbox/background processes and pending database journals before access.
- Automatically keep unsupported installations read-only; smart playlists are excluded.

### Audio preview and waveform

- Play/pause local audio, seek by clicking the waveform, and use Space for transport.
- Switch tracks with Up/Down, wrapping through the playlist while preserving edits.
- Zoom up to 64× using buttons, the zoom menu or the mouse wheel, then pan horizontally.
- Review the current grid in red: proposed changes after preparation, saved Rekordbox timing beforehand. Beat 1 is thick and beats 2–4 are thin; zoom in to see individual beats.
- Resize the waveform/playlist areas using the draggable divider.
- Playlist selection, preparation options and review filters sit above the waveform.
  Track rows begin directly beneath the waveform deck, with its playback and marker controls.
- Choose a waveform in **Settings → Waveform appearance**: Classic bars, Smooth filled,
  Frequency-coloured, Three-band, Bass-focused or Stereo. The choice applies immediately
  and is remembered across restarts without changing cues or grids.
- Frequency views reuse saved Rekordbox bands when available. The audio fallback uses
  native-rate filters (bass below 250 Hz, mids 250–2,500 Hz, highs above 2,500 Hz;
  cutoffs scale down for low sample-rate sources). Orange indicates
  bass, green mids and blue highs in Frequency-coloured and Three-band views.
  Bass-focused uses blue over a faint grey amplitude outline. Stereo preserves left/right balance; mono files show
  one lane. Multichannel files show their first two channels in Stereo. Saved detailed
  waveforms retain their original sample resolution; audition precise cue points.

### Beat-grid review

- Analyse a playlist in the background with per-track results and errors.
- Suggest small beat-alignment and tempo-drift corrections from audio transients.
- Set the first drop as bar 1 manually, without changing the tempo.
- Analyse grids only, memory cues only, or both together.
- Recalculate cues after a grid change.
- Refuse unsupported grid writes, including variable tempo and out-of-bounds adjustments.

### Drop markers and memory cues

- Suggest first and second drops using changes in bass energy.
- Drag both drop markers, or edit their positions in seconds.
- Snap markers to beats, snap to bar starts, or turn snapping off.
- Zoom directly to either drop; prevent the two markers from crossing.
- Rebuild countdown cues every 64 beats (16 bars in 4/4) before the drops.
- Retain manual anchors and flag edits that still need a cue rebuild.
- Budget up to ten memory points/loops and flag short intros, tight drop gaps or lack of slots.
- Keep existing memory cues by default, or explicitly replace ordinary memory cues.
- Preserve hot cues and saved loops; review the proposed cue list before import.

### Import, backups and recovery

- Import reviewed playlist grids and/or memory cues with one batch confirmation
  on the verified macOS/Rekordbox combination.
- Skip and list tracks with analysis errors or cues that still need rebuilding.
- Stage and validate changes before replacing the database and changed analysis files.
- Create timestamped backups with checksums and an operation manifest.
- Browse backups, choose a backup location and restore the connected library when safe.
- Refuse stale imports or restores that would overwrite newer library changes.
- Roll back caught installation failures and provide recovery for interrupted operations.
- Leave audio files unchanged and retain every backup until you remove it yourself.

### Diagnostics and privacy

- Export local diagnostics containing schema columns and aggregate counts, without
  track titles, audio paths or the database key.
- Process audio locally, with no telemetry, cloud processing or automatic uploads.
- Keep preview audio caches, backups and diagnostics on your computer.

See [cue rules](#cue-rules), [analysis limitations](#analysis-limitations), and
[backups and local data](#backups-and-local-data) for the exact boundaries.

## Current status: local preview 0.3.73

Organiser supports dragging scanned tracks onto existing or draft playlists in the left browser.
Click a row to select it, Cmd/Ctrl-click to toggle individual tracks, or Shift-click for a range.
Checkboxes and “Select all matching” share the same selection, including selected tracks on other pages.
Dragging a selected row keeps the group together. The destination playlist is outlined in blue;
folders expand on hover and the tree scrolls near its edges. Drops queue assignments for Imports,
skip tracks already in the destination, and preserve existing memberships. Tracks queued into
a playlist immediately leave the unassigned filters and their selection is cleared there;
discarding those assignments restores them. They remain visible in All tracks and the destination playlist. Folder and playlist
reordering remains available separately. No Rekordbox files change until the queued import is applied.

Choose playlists and select a track to view its saved Rekordbox waveform, grid
and existing cues immediately. The track list automatically loads compact bass-focused
waveforms before each title, with transparent backgrounds and small red triangles above the waveform for saved memory cues.
Saved bass data is reused where available; missing waveforms or bands are generated
from audio in the background. Browsing never prepares changes or queues imports.
Switching playlists cancels pending preview work, and a bounded session cache avoids
reloading recent previews. Offline audio can still show its saved waveform; if bass
data is also missing, only the available full waveform and cue markers are shown.
The main deck reads saved analysis and audio header metadata when selecting a track.
If detailed saved data is unavailable, the main preview says so. Styles requiring missing bands or stereo
channels show amplitude until preparation. Playback becomes available after the
audio timing checks during preparation.

The waveform shows one current beat grid: the proposed grid after preparation,
or the saved Rekordbox grid beforehand. At beat-level zoom, beat 1 of each 4/4
bar is thick red and beats 2–4 are thin red. The original and proposed grids are
not overlaid; whole-track views reduce marks to spaced bar starts for legibility.

Select **Scan & prepare playlist** below the track list. The On/Off toggle buttons beside the scan action choose
whether to set cues, fix beat grids, or both. Review the proposals, then import from **Imports**. Preparation reuses Rekordbox's
saved detailed waveform, BPM and original grid. It does not rerun key analysis or
estimate a new tempo in the cue workflow. The audio is still decoded for drop and
grid timing checks; the same pass provides the Stereo view. Rebuilding markers
uses the prepared results without rereading audio.

**Ignore cued tracks** skips and hides tracks with saved memory cues,
hot cues or loops. This option is off by default. Saved cues are checked again at
scan start; proposed cues remain visible until imported. Ignored tracks are
excluded from scan and import counts. Switch the option Off to show all tracks again.

After preparation, yellow rows highlight tracks needing review. **Show → Needs
review only** hides ready/imported tracks; hover a row for its reason. **Confirm
review**, beside Rebuild, accepts the current markers, grid and cues after listening
without moving them or importing. It clears automatic detection uncertainty, but
missing markers, stale cues and invalid grid changes still require correction.
Manual rebuilding keeps both chosen drop positions and creates cues even when
the other drop is off the translated grid. The offset is shown for review; BPM
stays unchanged. Rebuilt tracks remain yellow until **Confirm review** explicitly
accepts the timings. Automatic preparation also finishes a reviewable cue proposal
when the second drop is off-grid or audio-to-waveform matching is uncertain.
**Confirm review** accepts that existing result without regenerating cues, moving
markers or changing BPM. Only incomplete results or subsequent marker/grid edits
require rebuilding. Unconfirmed proposals remain excluded from import.
Review tracks open at 16× zoom around Drop 1. Confirming advances to the next review track and focuses its first drop; manual zoom and pan are kept while working on the current track. Editing markers cancels their acceptance. **Auto cue review tracks** retries automatic cue placement
for that group using the existing Rekordbox grids. It leaves ready/imported tracks
and manual drop edits untouched. This retry checks audio again; it does not change
grids or import anything. Uncertain drops, unavailable audio and unmatched waveform
timing remain flagged. Successful retries are labelled **Cues ready**, and the
import summary explicitly identifies cues-only changes. Filtering does not change
the scanned playlist scope or limit the import to the visible rows.

Saved PWV5/PWV3 amplitude and PWV7 band data are read without modifying the ANLZ
files. Detailed samples retain their 150-point-per-second clock. If detailed data
is missing, malformed or has an incompatible duration, the display explicitly
labels an audio fallback; missing frequency bands alone are generated from audio.
Band display scaling is shared across low/mid/high, rather than claiming to match
Rekordbox's proprietary rendering exactly.

Decoded MP3 audio can omit padding present in Rekordbox's saved timeline. The app
checks the audio against the saved waveform in five regions and accepts a timing
translation only when at least three clear matches agree within one saved sample.
Proposed cues, grid, stereo display and playback then share the saved timeline;
tempo is unchanged. Uncertain matches block automatic import for manual review.


**Direct beat-grid and memory-cue import is enabled for Rekordbox 7.2.19.0342 on macOS.**
The app reads regular playlists from the encrypted library. With **Fix beat grid**
and **Set memory cues** enabled, it shifts the original grid to the first drop
without changing BPM, checks the second drop against a bar start (25 ms tolerance),
then generates memory cues at exact grid timestamps. Automatic analysis also checks
drum timing across the track; ambiguous matches remain flagged. Grid-only analysis
retains the earlier conservative timing/drift suggestion method. One batch import saves both the grid and cues; there is no
manual XML workflow. Verified backups cover the database and changed analysis files.
Audio, existing hot cues and saved loops are preserved.

The writer supports constant-tempo 4/4 local MP3/WAV tracks at 44.1 or 48 kHz.
Drop detection combines bass-energy changes and drum activity, then searches within
one bar of each broad candidate for a leading attack with sustained bass contrast.
When two nearby attacks fit the same bass transition, refinement rejects a much
weaker pickup immediately before the main attack instead of always choosing the
earliest candidate. Comparable leading kicks are retained.
These are kick-like attack heuristics, not isolated drum stems or a trained model.
Ambiguous transitions and weak rhythmic support are flagged. Review both markers
and use **Align to Drop 1** or **Align to Drop 2** to immediately put a bar start on
the chosen marker and rebuild cues. **Snap to kick** selects that drop as the pending
grid anchor even when its timestamp is already correct; use the matching Align button
to update the proposed grid. BPM and manually placed markers stay unchanged.
A disagreement between drops requires review: preparation keeps the detected
markers and generates cues at those positions for explicit **Confirm review**
after listening. A shift
cannot fix an incorrect BPM, so accepting the result does not guarantee that both
drops align with the grid.
The detector cannot guarantee correct musical drops, bar starts or half/double-time.
Check the grid against the waveform. Seek to the real first drop and use **Set drop 1 / bar 1 here**
when bar alignment is wrong, then **Rebuild cues**. This shifts the nearest beat to
that position and makes it beat 1 without changing tempo. Changing the grid invalidates
existing cue proposals until rebuilt. Drop-based shifts may remove a single beat
that falls outside the audio boundary; remaining beats keep their spacing. The writer
validates that this is a boundary trim and updates the ANLZ beat count and lengths.
Variable-tempo grids, larger boundary changes, shared/missing analysis files and
unsupported formats are refused.
Streaming/cloud-synced records and inconsistent cue caches also remain unsupported.
Other Rekordbox versions and Windows remain read-only. Rekordbox **7.0.9.0007** has not been validated for writing.

Integration evidence on 7.2.19.0342: native memory-cue records were captured from
32-second generated WAV and VBR MP3 files. The Manager imported ten cues into each,
then Rekordbox was reopened and displayed their timestamps and labels. Its cue-call
controls recalled the imported eight-second cue on both formats. The cue caches
remained consistent after Rekordbox saved and quit. Personal track records and playlists were unchanged by the Manager import. Applying
and restoring a copy of the native encrypted database also restored its original
SHA-256 exactly. Hardware/USB export and other Rekordbox versions remain untested.

Grid verification used native timing and BPM edits to establish the file format.
Manager then imported a changed tempo, beat times and bar numbering, plus ten cues,
into both generated WAV and VBR MP3 tracks. Rekordbox showed 122 BPM and recalled the
first imported cue at bar 1, beat 1 on both. The grids survived Rekordbox saving and
closing. A private-copy import/restore reproduced the original database and all
changed analysis files byte-for-byte. This verifies serialization, not automatic
musical correctness on arbitrary tracks.

Internal automated checks use generated audio and a separate test library.
No commercial music is bundled.

## Install on Windows

1. Download the Windows ZIP and choose **Extract All**.
2. Keep the entire extracted `Rekordbox Manager` folder together, including `_internal`.
3. Open `Rekordbox Manager.exe`. This preview is unsigned, so Windows may show an
   unknown-publisher/SmartScreen prompt. Only proceed if you trust this repository
   and downloaded the release here; do not disable system protection globally.
4. Close Rekordbox, confirm you have a library backup, then select your `master.db`.
   A common Windows location is `%APPDATA%\Pioneer\rekordbox\master.db`.
5. Follow the playlist review steps below. **Import remains disabled on Windows.**

A successful Windows build and synthetic smoke test are not verification against
an actual Windows Rekordbox library. Report compatibility problems with your app,
Windows and Rekordbox versions; do not attach your library database or music.

## Install on Mac and review a playlist

1. Unzip the download for your Mac's processor and move `Rekordbox Manager.app` to Applications.
2. Open it and read the startup notice. The current build is ad-hoc signed for
   testing, not Developer ID signed/notarized. macOS may require approval in
   System Settings → Privacy & Security (or System Preferences → Security & Privacy on older macOS). Do not disable Gatekeeper globally.
3. On the first screen, confirm Rekordbox is closed and your library is backed up.
   Click **Choose database…**, select `master.db`, then **Connect and continue**.
   The last successful connection is preselected next time; the confirmation
   remains unchecked. Missing files require choosing a location again, and failed
   connections do not replace the remembered database. Change library and export
   diagnostics from the **Settings** page in the top toolbar.
   The playlist workspace opens only after the library and first playlist load.
   Use **Change library…** in the workspace to select a different database.
   The file chooser starts
   at a detected default location when available. Custom library locations can
   be selected manually. Common Mac location: `~/Library/Pioneer/rekordbox/`.
4. Choose a playlist from the left-hand browser. **Fix beat grid** is enabled by default
   on a supported installation; keep **Set memory cues** enabled and click **Scan & prepare playlist**. Drag the divider between the deck and playlist to resize them. The
   Up/Down arrows switch tracks and update the preview, wrapping at the ends
   (except while editing time fields or using menus); Backups is in the top toolbar.
5. Press **Space** to play/pause the selected track (except while editing a text
   or time field). Click the waveform to seek. Use **+ / −**, the zoom menu or scroll over the
   waveform vertically to zoom up to 64×. Scroll sideways with a Mac mouse or
   trackpad to pan smoothly through the zoomed waveform; the horizontal scrollbar
   also works. Scrolling follows your system direction setting. Red ticks show one
   active grid mirrored above and below the waveform: the saved Rekordbox grid
   before preparation, then the proposed grid. Beat 1 is thick; beats 2–4 are thin.
   Memory cues have a vertical line and a small triangle flag, without text names
   on the waveform. The Drop 1/Drop 2 drag handles remain labelled.
   Zoom in to see each beat; the whole-track view shows fewer markers to stay readable.
   Saved detailed Rekordbox waveforms retain 150 samples per second and can be
   viewed before preparing cues. The generated audio fallback uses approximately
   1 ms peaks. Display detail is reduced to fit the available screen pixels.
6. Drag the **DROP 1** and **DROP 2** handles to adjust the anchors; they snap to
   beats by default and cannot cross each other. Choose **Snap: Bar** for bar starts,
   or **Snap: Off** for precise placement between beats. With **Fix beat grid** enabled,
   **Rebuild grid + cues** shifts the grid to whichever drop you edited last. That
   marker stays at your chosen millisecond, and the other marker also stays fixed.
   If the other drop is off-grid, the offset is shown for you to review. BPM is
   unchanged. Listen to the result, then click **Confirm review** to accept it.
   With grid correction off, rebuilding preserves the marker positions and changes
   cues only. Moving a marker alone does not change the grid. If the grid bar starts are wrong,
   seek to the actual first drop and click **Set drop 1 / bar 1 here** first. **Zoom 1 / 2** centres the
   view on that marker for precise placement. Seconds fields remain available.
   **Snap to kick** beside each drop searches the analysed audio for a distinct attack
   within 0.6 beat (at most 250 ms). Move the marker close to the intended kick first.
   No clear match leaves the marker unchanged and displays an explanation. Successful
   snaps preserve the attack time until rebuilding. Listen, then rebuild.
   The **Rebuild grid + cues** (or **Rebuild cues**) button turns amber and says **needed** after a drop edit.
   Click it to update the 16-bar countdown markers, then review the
   cue list. Moving an anchor requires rebuilding its cues and preserves the edit
   when switching between tracks. **Scan & prepare playlist** runs fresh automatic preparation
   and replaces manual edits; use Rebuild to retain them. Reopening the app requires
   fresh preparation.
7. After checking and editing the playlist, open **Imports** and click **Import all ready tracks**
   to save your changes across all prepared playlists. One final
   confirmation covers the batch. Tracks needing review or manually rebuilt tracks
   must first be accepted with **Confirm review**.
   Tracks awaiting review, with analysis errors or cues awaiting a rebuild are explicitly listed
   and skipped. The confirmation shows the backup location. Keep Rekordbox closed
   until the import succeeds, then reopen it to see the saved cues. Unsupported
   file formats or inconsistent database records stop the whole import before
   the original database is replaced.

Use **Diagnostics…** after connecting a real library to save a local report
of schema columns and aggregate counts. It omits music titles, audio paths and
the database key. This is useful for the next compatibility-testing step.

Import modifies the library only after the final confirmation. Reading, analysis
and marker editing remain read-only.

## Cue rules

- Automatic drop suggestions snap to bar downbeats. Manually rebuilt cues preserve
  the exact selected anchors, including their fractional beat offset.
- Count backwards in 64-beat steps (16 bars in 4/4), using actual grid timestamps
  so tempo changes are respected.
- Reserve both drops and, where possible, 48 bars before the second drop.
- Add the first-drop countdown towards the start; use remaining slots to extend
  the second countdown without crossing the first drop.
- Limit memory points plus saved memory loops to ten. Never force a marker at
  file start if it does not fit the countdown pattern.
- Preserve hot cues and all loops. Keep existing memory cues by default; the
  explicit Replace option replaces ordinary memory cues only.
- Flag insufficient slots, short gaps between drops, incomplete intros and
  invalid grids. Never silently exceed the slot budget.

## Analysis limitations

The current detector is a conservative signal-based prototype, **not a trained
music-structure model**. Drop suggestions compare bass-energy changes across
bars. They can identify builds, false drops or outros incorrectly. Manual anchor
review is required. Genres guide warnings, not hard tempo rules.

Grid analysis proposes small alignment/drift corrections where transients
support them. It does not automatically resolve half/double-time interpretations,
incorrect bar-one alignment, large tempo errors, or variable-tempo grids. Bar-one
alignment can be set manually at the first drop; larger/variable-tempo corrections
still need Rekordbox. Cues-only analysis never changes a grid.
Grid-only analysis never changes cue positions. Missing, silent, unsupported or
over-30-minute audio is reported per track.

Smart playlists are excluded rather than incorrectly treated as static playlists.
The reader refuses databases with outstanding journal data. If instructed, reopen
Rekordbox and quit it cleanly; never delete WAL/journal files to bypass the guard.
Cloud-sync write interactions are not supported. Writing is gated to the locally
verified Rekordbox version and local content records, not upstream compatibility claims.

## Backups and local data

Default data directories:

- macOS: `~/Library/Application Support/Rekordbox Manager/`
- Windows: `%LOCALAPPDATA%\Rekordbox Manager\`

Backups live in the `Backups` subdirectory. Change the location in the Backups
screen. Each timestamped backup contains original files and a manifest with
checksums, original paths, operation state, and expected post-operation hashes.
No backup is automatically deleted. Music files are never modified.

Memory-cue imports stage an encrypted database copy, update both `djmdCue` and
`contentCue`, advance the local update counter, and validate integrity and cue
read-back before replacing `master.db`. Backups include the original database,
plus every changed analysis file, but not audio or unchanged files. Grid writes
patch PQTZ, clear the secondary PQT2 cache like the native editor, and update BPM
metadata when needed. Other analysis tags and the .3EX embedding file stay unchanged. Source hashes, audio timestamps and
Rekordbox/agent process checks block stale or concurrent operations. Installation
uses a durable journal and rolls back caught failures when exclusive access can
still be established. Keep Rekordbox closed during the whole operation.

Restore is available in Backups for the same connected library. It refuses to
overwrite any newer database or analysis-file changes, including changes Rekordbox may save after
reopening. Recovery can release an interrupted Manager lock only after its process
has exited; then select the interrupted backup and restore it. A backup on the
same disk does not protect against disk failure. Process checks cannot eliminate
all races with external applications that do not honour the Manager's lock.

Backups and diagnostics are not uploaded. There is no telemetry, cloud processing, or auto-updater.

## Development

Python 3.12, macOS 12+ on Intel / 12.3+ on Apple Silicon, or Windows 10/11 (64-bit). Build and test each architecture
separately. Development on Apple Silicon does not produce an Intel executable
unless an Intel Python and Intel dependencies are used.

```sh
python3 -m venv .venv
# macOS
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -e '.[dev]'
python run.py
python -m pytest -q
python scripts/build.py
```

To prepare disposable audio for testing inside Rekordbox itself:

```sh
python scripts/prepare_rekordbox_test_audio.py
```

This writes three standard 44.1 kHz stereo PCM WAVs, a test playlist and a reference
manifest under `dist/Rekordbox Test Audio`. Import the test playlist into Rekordbox
and let its normal analysis finish. This is developer fixture setup; the Manager's
normal library connection does not require playlist exports/imports. These simple
signals are integration fixtures, not realistic benchmarks for the three genres.

For an Intel build on a newer macOS targeting Monterey, explicitly install the
older-platform NumPy/SciPy wheels before building (the versions also publish
macOS-14-only wheels, which pip otherwise prefers):

```sh
python -m pip download --dest build/monterey-wheels --platform macosx_12_0_x86_64 --only-binary=:all: --python-version 312 --implementation cp --no-deps numpy==2.2.6 scipy==1.15.3
python -m pip install --force-reinstall --no-deps --no-index --find-links build/monterey-wheels numpy==2.2.6 scipy==1.15.3
```

The build script audits embedded binaries and fails if any requires macOS newer
than the app declares: 12.0 on Intel or 12.3 on Apple Silicon. This is a compatibility check, not a substitute for testing on Monterey.

Set `REKORDBOX_MANAGER_DATA_DIR` to a disposable directory for UI/testing sessions.
The tests use generated audio, artificial ANLZ files, and plain/encrypted SQLite
fixtures; they do not access a personal Rekordbox library. GUI tests use Qt's
offscreen platform. Sandbox environments may need permission for Qt's CPU and
process queries.

The [GitHub Actions workflow](.github/workflows/build.yml) tests and builds Windows
x64, Intel Mac and Apple Silicon Mac separately. Each frozen executable must pass
the synthetic self-test (GUI, analysis, cue editing, demo import/restore, encrypted
database dependency and media decoder) before its ZIP is uploaded. Mac builds also
pass the embedded-binary audit against their declared minimum macOS version. These checks do not replace
real-library testing on each supported OS/Rekordbox version.

To publish a subsequent preview:

1. Update the version in `pyproject.toml`, `rekordbox_manager/__init__.py` and the
   startup notice in `rekordbox_manager/ui.py`; update this README's download links.
2. Add `docs/releases/v<VERSION>.md` with the changes and known limits.
3. Push a matching `v<VERSION>` tag, or run the workflow on `main` with **publish**
   enabled. The release job waits for all three builds, verifies their checksums,
   uploads every package to a draft and then publishes the complete preview.

Ordinary pushes and pull requests only test/build; they do not publish releases.
Do not overwrite a published version. Fixes need a new version and tag.
[Publishing script](scripts/publish_release.py) also supports publishing downloaded
CI artifacts with `GITHUB_REPOSITORY` and `GITHUB_SHA` set to the tested repository
and commit. This is useful for publishing the first release after its main-branch
build passes. No signing credentials are configured.

## Before expanding write support

- Capture and compare native records on 7.0.9 and each additional supported version.
- Verify more audio encodings and sample rates, existing hot cues/loops inside
  Rekordbox, hardware/USB export, and restoration after interrupted sessions.
- Expand grid correction only with additional musical validation. Turning off
  Fix beat grid keeps the existing grid and writes memory cues only.
- Validate Windows and cloud-sync interactions independently before enabling them.

## Sharing

Source and downloads are hosted at
[wetenhall/rekordbox-manager](https://github.com/wetenhall/rekordbox-manager).
A project source-code licence has not yet been selected. Third-party components
retain their own licences; their notices are bundled in each download under
`third-party-notices` inside the app's resources. Public visibility does not grant
write access to this repository; proposed changes go through pull requests.

The app is unofficial and is not affiliated with AlphaTheta/Pioneer DJ.

Technical references: [pyrekordbox](https://github.com/dylanljones/pyrekordbox),
[ANLZ format](https://pyrekordbox.readthedocs.io/en/latest/formats/anlz.html),
[Rekordbox manual](https://cdn.rekordbox.com/files/20260409151936/rekordbox7.214_manual_EN.pdf).

### Hold-to-play Cue control

The **Cue** button beside Play auditions a temporary playback cue without creating a memory cue.
While paused, seek or use **Zoom 1 / Zoom 2** to choose a position. Hold Cue to play from it;
release to pause and return. During normal playback, Cue starts from the last paused cue position.
Changing tracks resets this temporary cue. Leaving the app/tab, starting a scan or changing the
audio source cancels a held audition. Space always toggles play/pause in the deck, including when Cue is focused.
After scanning or choosing a mode/filter, focus returns to the waveform so Space and
Up/Down work immediately. Clicking a waveform or track also restores these shortcuts.

Preparation errors are shown beneath the waveform controls. If existing memory points fill
all ten slots and replacement is off, enable **Replace memory cues** and scan again to replace
those points, or use **Check saved cues** to compare and confirm a replacement for one track.
