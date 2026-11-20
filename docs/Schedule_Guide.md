# Lynx Deck: The Schedule

The Deck runs your repeater's day by itself: the clock before the hour, the
programmes, the test cards, and the programme guide that Lynx-Tx puts on air.
It takes over from Bitfocus Companion's time-of-day triggers, so the schedule
lives in one place.

- **Cuts on time:** At a time of day on chosen days, or every hour at mm:ss.
- **On-air times:** Allows for the delay to air, so a 19:00 programme reaches
  viewers at 19:00.
- **The programme guide:** Entries you tick become the EPG, which Lynx-Tx reads
  from the Deck.
- **Back on its feet after a restart:** Rejoins whatever should be on air,
  part way through.
- **Moving over is quick:** Imports your existing Companion triggers.

## What you need

- **Lynx Deck 1.7.0 or later.** The Deck's page shows its version at the top.
- **The Pi's clock on NTP.** Raspberry Pi OS does this by default. On the Deck,
  `timedatectl` should say "System clock synchronized: yes".
- **For the guide on air:** Lynx-Tx with the guide taken from the Deck (beta
  from 20 Nov 2026).

## The Schedule page

Click **Schedule** at the top right of the Deck's page, or go to
`http://<deck>:8080/schedule`. From top to bottom:

1. **On air now (by the schedule):** The entry the schedule says is on air,
   and since when. The clock at the right is the Deck's own.
2. **Add an entry** (or **Change an entry** when you are editing one).
3. **The schedule:** Every entry, the one on air now highlighted.
4. **The guide, next 24 hours:** The programmes as viewers' receivers will
   show them.
5. **Import from Companion.**

## Times are on-air times

Every time on the Schedule page is the moment you want **viewers** to see the
change. The Deck cuts early by the **Clock ahead by** setting (on the Deck's
main page, under Settings), which is your delay to air: about 3 to 4 seconds
through Lynx-Tx. So:

- **Don't take the delay off yourself.** For the clock to be on screen at
  59:30, enter 59:30, not 59:26.
- **Measure the delay once,** with the station clock: put it up, watch it off
  air next to a phone, and set **Clock ahead by** to the difference. The clock
  and the schedule both use it.

## Adding an entry

| Box | What to put |
|---|---|
| **Repeat** | *At a time of day*, or *every hour, at minutes:seconds* |
| **Time** | A time of day as `19:00` or `19:00:15`; or for every hour, minutes and seconds past the hour, such as `59:30` |
| **Days** | The days it runs. *all* ticks every day. |
| **Clip** | What to cut to: any clip in the Deck's list |
| **In the guide** | Tick it if this is a programme for the guide (EPG). Leave it unticked for the clock, idents and fillers. |
| **Guide title** | Shown when *In the guide* is ticked. Left empty, the clip's name is used (`Film_Night.mp4` becomes "Film Night"). |
| **Guide length** | In minutes. Left empty, an hour, or until the next programme if that comes first. |
| **On** | Untick to keep an entry without it running. |

Press **Save**. **Cancel** leaves without saving; it never deletes anything.

In the schedule list:

- **change:** Opens the entry in the form above.
- **switch off / switch on:** Stops or restarts an entry without losing it.
- **delete:** Removes it, after asking.

## What happens after a cut

The schedule only decides **when** a clip starts. What it does next is the
clip's own **At end** setting in the Deck's clip list, exactly as before:

| At end | After the cut |
|---|---|
| **hold** | Stays on its last frame (or the still) until the next entry. Use this for test cards and the clock. |
| **loop** | Plays round and round until the next entry. |
| **once** | Plays once and stops. |
| **auto** | Moves on to the next clip in the list; a still moves on after the still duration. |

**Test cards and other stills want hold,** or they move on after a few
seconds.

## The station clock in the schedule

Add the clock as one entry:

- **Repeat:** every hour
- **Time:** 59:30 (the top-of-the-hour sound starts at 59:30, so the music
  plays from its first note)
- **Clip:** your clock face, set to **hold**
- **In the guide:** unticked

Put your programmes at **hh:00:15** or so, after the announcement has finished.
A second before a scheduled cut away from the clock, the clock fades to black,
and the next programme comes up out of the black.

See the [Station Clock Guide](Station_Clock_Guide.md) for making the face and
the sound.

## The programme guide

Entries with **In the guide** ticked are the guide. Each programme runs from its
time for its guide length, but never into the next one. The *guide, next 24
hours* panel shows what receivers will show.

Lynx-Tx takes the guide from the Deck: on its **EPG and time** card, put the
Deck's address (for example `192.168.40.117:8080`) and press **Refresh**. It
asks again every 30 minutes, and if the Deck doesn't answer, the last guide
stays on air. The Deck is the only source: Companion's EPG triggers are no
longer read.

## After a restart

When the Deck starts, it looks at the schedule and puts on whatever should be
on air now:

- **A film** that started at 19:00, with the Deck back at 19:20, joins 20
  minutes in.
- **A looping clip** joins at the right point in its loop.
- **A still on hold** (a test card, the clock) simply comes back up; the
  clock's sound joins part way if it's mid-junction.
- **If the clip would have finished,** the Deck stays on its default slide
  until the next entry.

This only happens at start-up. If someone cuts to something else by hand (from
the Deck's page, the ATEM or Companion), the Deck stays there until the next
scheduled entry.

## Moving over from Companion

The import reads Companion's switched-on **time-of-day** triggers that cut the
Deck to a clip (its *go to clip by name* or *go to clip* action):

- **`EPG:` triggers** become programmes in the guide, with the title and length
  from the trigger's name ("EPG: Film Night (2h)": Film Night, 120 minutes).
- **Other playout triggers** (the clock) come in outside the guide.
- **The same clip at the same minutes and seconds every hour** becomes one
  hourly entry: 24 clock triggers become "every hour at 59:40".
- **Switched-off triggers,** and those that only drive the ATEM or anything
  else, are left alone.
- **Entries already on the Deck** are skipped, so importing twice is safe.
- **A clip that isn't on this Deck** comes in switched off, with a note.

To import:

1. **Either** type Companion's address (for example `192.168.40.103:8000`) and
   press **Import**,
2. **or** choose an export file: in Companion, *Import / Export*, export the
   full configuration (compressed, JSON or YAML all work).
3. Read the notes under the button, then check the entries.

Then hand over:

1. **Compare** the Deck's schedule with Companion's triggers.
2. **In Companion,** remove the HyperDeck actions (go to clip, wait, play) from
   the triggers the Deck now does, or switch those triggers off. Keep any
   actions that drive the ATEM (the DOG), as the Deck can't do those.
3. **Point Lynx-Tx's guide at the Deck,** as above.

Imported times become on-air times, so each cut now happens *Clock ahead by*
earlier than Companion did it. That is what you want, but it explains a few
seconds' difference if you compare the two.

**Never run both.** If Companion and the Deck cut at the same times, they fight
over the picture.

## Troubleshooting

| What you see | What to check |
|---|---|
| Nothing happens at the time | Is the entry **On**? Is today one of its **Days**? Does the clip exist (the list says *not in the library* if not)? |
| The cut is a few seconds out on air | **Clock ahead by**: measure the delay with the station clock. |
| A test card disappears after a few seconds | Set the clip's **At end** to **hold**. |
| The schedule cuts at the wrong hour | The Deck's clock: `timedatectl`, and the time zone. |
| The guide is missing a programme | Tick **In the guide** on its entry; the *guide, next 24 hours* panel shows the result. |
| Lynx-Tx's guide hasn't changed | Press **Refresh** on its EPG card, or wait up to 30 minutes. |
| Something else | The Deck's log: `journalctl -u lynx-deck --since "10 min ago" \| grep -i schedule` |

The schedule is kept in `schedule.json` beside the Deck's settings file, so
updates never touch it.

## Test checklist

1. Import from Companion (or add a few entries by hand). Check the times, days,
   clips and guide titles against Companion.
2. Set **Clock ahead by** from a measurement off air.
3. Add a test entry a few minutes ahead: it cuts on time, as seen off air.
4. Leave it over an hour: the clock at 59:30, the junction, the programme after.
5. Switch an entry off: it doesn't run. Switch it on again.
6. Tick and untick **In the guide** on an entry: the guide panel follows.
7. Point Lynx-Tx's EPG card at the Deck and press Refresh: the guide on a
   receiver matches the Deck's panel.
8. Restart the Deck part way through a programme
   (`sudo systemctl restart lynx-deck`): it rejoins at the right point.
