# Lynx Deck: The Station Clock

A Deco-style station clock for your repeater, drawn live by the Deck from the
Pi's own clock, with the Greenwich pips and your own time announcement at the
top of every hour.

- **Live hands:** Hour, minute and a sweeping (or ticking) second hand, drawn
  over a clock-face still while it is on screen.
- **Your station's face:** Call sign, town and web address on the face, made
  by the Deck from its web page.
- **The top of the hour:** Music from 59:30, the six pips, then your
  announcement ("It's eleven o'clock on GB3OO"), all timed to the clock.
- **Allows for the delay to air:** The clock runs a few seconds ahead so that
  viewers see and hear the right time.

## What you need

- **Lynx Deck 1.6.0 or later.** Press *Check for updates* on the Deck's web
  page.
- **The Pi's clock on NTP.** Raspberry Pi OS does this by default. On the Deck,
  `timedatectl` should say "System clock synchronized: yes".
- **Two Python packages** for drawing the face and building the sounds:

  ```
  sudo apt install -y python3-numpy python3-pil
  ```

## Step 1: Make your clock face

On the Deck's web page, find the **Station clock** panel.

1. **Call sign:** For example GB3OO.
2. **Town:** For example FOLKESTONE.
3. **Web address:** For example gb3oo.co.uk. It is shown in the face's small
   capitals.
4. **Clip number:** The number the face's file name starts with (20 gives
   `20_GB3OO_Clock.png`). It only decides where the face sits in the list,
   which is in file-name order. If you call clips up by name, as Companion can,
   any number will do. If anything calls them by number, such as the ATEM's own
   HyperDeck control, pick one that sorts after your existing clips, so their
   numbers don't move.
5. Press **Make clock face**.

The face appears in the clip list as, for example, `20_GB3OO_Clock.png`. Change
any detail and press the button again to redraw it.

Any still whose name ends in `Clock` is treated as a clock face, so a face you
made earlier and uploaded by hand still works.

## Step 2: Set the clip to hold

In the clip list, set the face's **At end** to **hold**. Otherwise the Deck
moves on to the next clip after the still duration.

## Step 3: Call it up

The clock is a clip like any other:

- **From the web page:** Click its row, then **Play**.
- **From the ATEM or Companion:** Go to its clip number and play.

It fades up from black over half a second, so the face and hands arrive
together. Go to any other clip to take it off.

**It must be playing, not just cued.** The hands show either way, but the
Deck makes no sound while paused, so the top of the hour would be silent.

## Step 4: Allow for the delay to air

Your viewers see the picture a few seconds after the Deck sends it (encoding,
the transmitter, their receivers). To make the clock right on air:

1. Put the clock up and watch it off air, next to a phone showing the time.
2. Note how far behind the phone it is: 3 to 4 seconds is typical.
3. In **Settings**, set **Clock ahead by** to that figure and save. It takes
   effect at once.

The hands and the top-of-the-hour sound both use this setting. If Companion
cuts to the clock at a set time, make that trigger the same amount earlier
(58:56 for a clock at 59:00 with a 4 s delay).

**Second hand:** *Sweep* (smooth) or *tick once a second*, in the same
Settings panel.

## Step 5: The top of the hour

While the clock is playing, at every hour:

| Time | What you hear |
|---|---|
| 59:30 to 59:50 | Your music (20 s), if you have uploaded some |
| 59:50 to 59:55 | Silence |
| 59:55 to 59:59 | Five short pips, 0.1 s each, on each second |
| 00:00 | The long pip, 0.5 s. Its start is the hour. |
| 00:01 | Your time announcement for the new hour |

A Deck with no sounds of its own plays the pips alone. If the clock is put up
part way through, the sound joins at the right point.

### Recording your announcements

- **Twelve files,** one per hour, 1 to 12. The same set is used morning and
  afternoon.
- **Names ending in the hour:** For example `gb3oo_1.mp3` to `gb3oo_12.mp3`.
- **Short:** Under 3.5 seconds, starting to speak straight away (no more than
  a fifth of a second of silence at the start).
- **Level:** Speech peaking at PPM 4 to 5 (about -18 to -14 dBFS on a PPM, so
  about -10 dBFS on a sample-peak meter). The pips are set at the equivalent of
  an -18 dBFS line-up tone.
- **Format:** MP3, WAV, AIFF, M4A, AAC, FLAC, OGG or Opus. Mono is fine.

### Music

- **Twenty seconds,** ideally arranged to end at 20 s. Anything longer is
  faded out over its last second.
- **Same level as the speech.**
- **A name containing "music",** for example `lillibullero_music.wav`.
- **Rights:** Use only music you have permission to broadcast.

### Uploading

Drop all thirteen files (the twelve announcements and the music) on the
**Station clock** panel at once, or use *choose files*. The Deck saves them
and then builds its twelve top-of-the-hour sounds, which takes about a minute.
The panel then shows which hours have announcements, the music, and when the
sounds were built.

- **To replace one announcement:** Drop the new file. A name ending in the same
  number replaces the old one.
- **To remove the music:** Click *remove* beside it.

Everything you upload is kept in `/srv/lynxdeck/clock`, outside the Deck's
software, so updates never touch it.

## Troubleshooting

| What you see | What to check |
|---|---|
| No hands | The face's file name must end in `Clock`. |
| The time is wrong | `timedatectl` on the Deck: the clock must be synchronised. |
| Right on the Deck, early or late on air | Change **Clock ahead by**. |
| No sound at the top of the hour | The clock was cued but not playing; press **Play**. Also check the Deck's HDMI sound reaches the ATEM or transmitter. |
| "No module named numpy" or "PIL" | `sudo apt install -y python3-numpy python3-pil` |
| Something else | The Deck's log: `journalctl -u lynx-deck --since "10 min ago"`. Look for lines with "clock" or "top of the hour". |

## Test checklist

1. Make the face from the panel. Check the call sign, town and web address.
2. Set it to hold, put it up and press play: it fades up with all three hands.
3. Measure the delay and set **Clock ahead by**. The clock should match a phone
   off air.
4. Upload the twelve announcements and the music. The panel should show all
   twelve hours and the music.
5. Leave the clock up over an hour: music at 59:30, pips from 59:55, the long
   pip as the minute hand reaches 12, then the announcement.
6. Leave it up over a second hour: it should do the same without help.
7. Put it up at about 59:40: the sound should join part way, in time.
8. Cue it without playing over an hour: silent, and the log says why.
